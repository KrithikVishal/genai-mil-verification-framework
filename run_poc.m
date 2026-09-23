% run_poc.m
% =========================================================================
% Main Entry Point for PoC-1: GenAI-Driven MIL Verification Framework
% Adaptive Cruise Control (mpcACCsystem) — Native MATLAB R2024a Execution
% =========================================================================

clc; clear; close all;
t_start = tic;

root_dir = fileparts(mfilename('fullpath'));
addpath(fullfile(root_dir, 'src', 'matlab'));
addpath(fullfile(root_dir, 'tests', 'matlab_mil'));
addpath(fullfile(root_dir, 'results'));

fprintf('======================================================================\n');
fprintf('  PoC-1: GenAI-Driven MIL Verification Framework (MATLAB R2024a)\n');
fprintf('  Target System: Adaptive Cruise Control (MPC Baseline)\n');
fprintf('  Verification Mode: Option B (Shift-Left SIL / Target-Fitness Screening)\n');
fprintf('======================================================================\n\n');

%% STEP 1: Load EARS Requirements
fprintf('======================================================================\n');
fprintf('  STEP 1: Load Formal EARS Requirements\n');
fprintf('======================================================================\n');
reqs = {...
    'ACC-REQ-001', 'speed_tracking',      'Maintain ego speed within ±0.5 m/s of V_set in steady-state';...
    'ACC-REQ-002', 'safe_distance',       'Reduce speed so D_actual >= D_safe within 3 s';...
    'ACC-REQ-003', 'distance_formula',    'Compute safe distance as D_safe = 10 + 1.4 * V_ego';...
    'ACC-REQ-004', 'acceleration_bounds', 'Constrain acceleration to [-3.0, 2.0] m/s^2';...
    'ACC-REQ-005', 'mode_switch',         'Transition to spacing-control mode within 0.1 s on trigger'...
};
for i = 1:size(reqs, 1)
    fprintf('  %-13s [%-20s]  %s\n', reqs{i,1}, reqs{i,2}, reqs{i,3});
end
fprintf('\n');

%% STEP 2: MIL Baseline Verification (float64)
fprintf('======================================================================\n');
fprintf('  STEP 2: Run MIL Baseline Test Suite (MATLAB Engine, float64)\n');
fprintf('======================================================================\n');
mil_results = run_all_mil_tests('float64');

passed_mil = 0;
for i = 1:length(mil_results)
    if mil_results{i}.passed
        passed_mil = passed_mil + 1;
    end
end
fprintf('  MIL Baseline Summary: %d/%d requirements PASSED in MATLAB.\n\n', passed_mil, length(mil_results));

%% STEP 3: Option B — Target-Fitness Screening (Shift-Left SIL)
fprintf('======================================================================\n');
fprintf('  STEP 3: Option B — Target-Fitness Screening (Precision & Rate)\n');
fprintf('======================================================================\n');
[prec_results, ts_results] = TargetFitnessDegrader.run_full_screening();

%% STEP 4: Traceability Matrix
fprintf('\n======================================================================\n');
fprintf('  STEP 4: Requirements Traceability Matrix\n');
fprintf('======================================================================\n\n');
fprintf('  %-13s %-22s %-12s %s\n', 'Req ID', 'Category', 'MIL Result', 'Artifact Path');
fprintf('  %s\n', repmat('-', 1, 75));
for i = 1:size(reqs, 1)
    res_str = 'PASS';
    if ~mil_results{i}.passed, res_str = 'FAIL'; end
    test_path = sprintf('tests/matlab_mil/test_acc_req_%03d.m', i);
    fprintf('  %-13s %-22s %-12s %s\n', reqs{i,1}, reqs{i,2}, res_str, test_path);
end
fprintf('  %s\n\n', repmat('-', 1, 75));

elapsed = toc(t_start);
fprintf('======================================================================\n');
fprintf('  MATLAB PoC-1 execution completed successfully in %.2f seconds.\n', elapsed);
fprintf('  Generated artifacts:\n');
fprintf('    results/matlab_scorecard.txt  (ASCII Target-Fitness Report)\n');
fprintf('    results/matlab_scorecard.png  (Multi-panel MATLAB Plot)\n');
fprintf('======================================================================\n\n');
