function result = mvp_run_test(intent_json_path, output_json_path)
% mvp_run_test.m
% -----------------------------------------------------------------------
% MVP MATLAB Builder + Runner
% Called by the Python MVP loop via subprocess.
%
% Args:
%   intent_json_path  - path to validated Test-Intent JSON file
%   output_json_path  - path where Execution-Result JSON will be written
%
% The function:
%   1. Loads the Test Intent JSON
%   2. Builds the closed-loop simulation from intent parameters
%   3. Runs ACCController + PlantModel
%   4. Evaluates all oracle conditions
%   5. Writes a machine-readable Execution Result JSON
% -----------------------------------------------------------------------

root_dir = fileparts(mfilename('fullpath'));
addpath(fullfile(root_dir, '..', '..', 'src', 'matlab'));

t_start = tic;
run_id  = sprintf('RUN-%s', datestr(now, 'yyyymmdd-HHMMSS'));

%% Step 1 — Load Test Intent
try
    raw  = fileread(intent_json_path);
    intent = jsondecode(raw);
catch ex
    result = build_error_result('UNKNOWN', run_id, ...
        'config_error', sprintf('Failed to load intent JSON: %s', ex.message));
    write_json(result, output_json_path);
    return;
end

test_id        = intent.test_id;
req_id         = intent.requirement_id;
duration_s     = intent.duration_s;
Ts             = intent.sample_time_s;
ic             = intent.stimulus.initial_conditions;
v_ego_init     = ic.v_ego_init_mps;
v_lead_init    = ic.v_lead_init_mps;
d_init         = ic.d_init_m;
v_set          = ic.v_set_mps;
events         = intent.stimulus.events;
eval_start     = intent.oracle.evaluation_window_start_s;
eval_end       = intent.oracle.evaluation_window_end_s;
oracle_conds   = intent.oracle.conditions;

%% Step 2 — Build & Run Simulation
try
    ctrl  = ACCController(Ts, 'float64');
    plant = PlantModel(Ts);
    plant.reset(v_ego_init, d_init, v_lead_init);

    n_steps = floor(duration_s / Ts);
    t_arr      = zeros(n_steps, 1);
    v_ego_arr  = zeros(n_steps, 1);
    v_lead_arr = zeros(n_steps, 1);
    d_actual_arr = zeros(n_steps, 1);
    a_cmd_arr  = zeros(n_steps, 1);
    d_safe_arr = zeros(n_steps, 1);
    mode_arr   = zeros(n_steps, 1);

    for i = 1:n_steps
        t = (i - 1) * Ts;

        % Apply any timed events
        for e = 1:length(events)
            ev = events(e);
            if abs(t - ev.time_s) < Ts/2 && strcmp(ev.type, 'lead_deceleration')
                if isfield(ev, 'decel_mps2')
                    plant.lead_decelerate(ev.decel_mps2);
                end
            end
        end

        s = plant.state();
        [a_cmd, mode] = ctrl.step(s.v_ego, s.v_lead, s.d_actual, v_set);
        plant.step(a_cmd);

        t_arr(i)       = t;
        v_ego_arr(i)   = s.v_ego;
        v_lead_arr(i)  = s.v_lead;
        d_actual_arr(i) = s.d_actual;
        a_cmd_arr(i)   = a_cmd;
        d_safe_arr(i)  = ctrl.d_safe(s.v_ego);
        mode_arr(i)    = mode;
    end
catch ex
    result = build_error_result(test_id, run_id, ...
        'runtime_error', sprintf('Simulation error: %s', ex.message));
    result.requirement_id = req_id;
    write_json(result, output_json_path);
    return;
end

%% Step 3 — Evaluate Oracle in the evaluation window
eval_mask = (t_arr >= eval_start) & (t_arr <= eval_end);

% Map signal names -> arrays (raw + computed)
sig_map.v_ego       = v_ego_arr;
sig_map.v_lead      = v_lead_arr;
sig_map.d_actual    = d_actual_arr;
sig_map.a_cmd       = a_cmd_arr;
sig_map.d_safe      = d_safe_arr;
sig_map.mode        = mode_arr;
% Computed signals — most useful for oracle conditions
sig_map.speed_error = abs(v_ego_arr - v_set);        % |v_ego - v_set|  (m/s)
sig_map.gap_surplus = d_actual_arr - d_safe_arr;     % d_actual - d_safe  (m)

all_pass    = true;
cond_results = {};
warnings    = {};
errors      = {};

for c = 1:length(oracle_conds)
    cond   = oracle_conds(c);
    sig_name = cond.signal;
    op       = cond.operator;
    thresh   = cond.threshold;

    if ~isfield(sig_map, sig_name)
        warnings{end+1} = sprintf('Unknown signal in oracle: %s', sig_name); %#ok<AGROW>
        all_pass = false;
        continue;
    end
    
    sig_window = sig_map.(sig_name)(eval_mask);
    
    switch op
        case '<='
            check = all(sig_window <= thresh);
            measured = max(sig_window);
        case '>='
            check = all(sig_window >= thresh);
            measured = min(sig_window);
        case '=='
            check = all(abs(sig_window - thresh) < 1e-9);
            measured = max(abs(sig_window - thresh));
        case 'abs<='
            check = all(abs(sig_window) <= thresh);
            measured = max(abs(sig_window));
        case '<'
            check = all(sig_window < thresh);
            measured = max(sig_window);
        case '>'
            check = all(sig_window > thresh);
            measured = min(sig_window);
        otherwise
            warnings{end+1} = sprintf('Unknown operator: %s', op); %#ok<AGROW>
            check   = false;
            measured = NaN;
    end
    
    if ~check, all_pass = false; end
    cond_results{end+1} = struct('signal', sig_name, 'operator', op, ... %#ok<AGROW>
        'threshold', thresh, 'measured', measured, 'passed', check);
end

%% Step 4 — Compute Summary Metrics
max_spd_err = max(abs(v_ego_arr(eval_mask) - v_set));
rms_spd_err = sqrt(mean((v_ego_arr(eval_mask) - v_set).^2));
min_gap_surplus = min(d_actual_arr(eval_mask) - d_safe_arr(eval_mask));
acmd_min = min(a_cmd_arr);
acmd_max = max(a_cmd_arr);

%% Step 5 — Build Execution Result
verdict = 'PASS';
if ~all_pass, verdict = 'FAIL'; end

wall_s = toc(t_start);

result = struct();
result.test_id             = test_id;
result.run_id              = run_id;
result.requirement_id      = req_id;
result.execution_status    = 'success';
result.requirement_verdict = verdict;
result.measured_metrics    = struct(...
    'max_speed_error_mps',  max_spd_err, ...
    'rms_speed_error_mps',  rms_spd_err, ...
    'min_gap_surplus_m',    min_gap_surplus, ...
    'a_cmd_min_mps2',       acmd_min, ...
    'a_cmd_max_mps2',       acmd_max ...
);
result.signal_traces       = struct(...
    'time',     t_arr', ...
    'v_ego',    v_ego_arr', ...
    'd_actual', d_actual_arr', ...
    'a_cmd',    a_cmd_arr', ...
    'd_safe',   d_safe_arr', ...
    'mode',     mode_arr' ...
);
result.oracle_conditions   = cond_results;
result.warnings  = warnings;
result.errors    = errors;
result.model_info = struct(...
    'controller',    'ACCController', ...
    'plant',         'PlantModel', ...
    'matlab_version', version ...
);
result.budget_used = struct('wall_time_s', wall_s, 'iteration', intent.iteration);

write_json(result, output_json_path);
end

% -----------------------------------------------------------------------
function r = build_error_result(test_id, run_id, status, msg)
    r.test_id             = test_id;
    r.run_id              = run_id;
    r.requirement_id      = 'UNKNOWN';
    r.execution_status    = status;
    r.requirement_verdict = 'ERROR';
    r.measured_metrics    = struct();
    r.signal_traces       = struct();
    r.oracle_conditions   = {};
    r.warnings            = {};
    r.errors              = {msg};
    r.model_info          = struct();
    r.budget_used         = struct('wall_time_s', 0, 'iteration', 0);
end

% -----------------------------------------------------------------------
function write_json(data, fpath)
    fid = fopen(fpath, 'w');
    if fid == -1
        error('Cannot open output path: %s', fpath);
    end
    fprintf(fid, '%s', jsonencode(data));
    fclose(fid);
    fprintf('  [MATLAB] Result written: %s\n', fpath);
end
