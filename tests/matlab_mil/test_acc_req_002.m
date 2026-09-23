function res = test_acc_req_002(dtype)
    % Test ACC-REQ-002: Safe Distance Spacing Recovery (d_actual >= d_safe)
    if nargin < 1, dtype = 'float64'; end
    
    Ts = 0.1;
    v_set = 30.0;
    d_init = 45.0;
    T_total = 15.0;
    
    ctrl = ACCController(Ts, dtype);
    plant = PlantModel(Ts);
    plant.reset(30.0, d_init, 30.0);
    
    n_steps = floor(T_total / Ts);
    t_arr = zeros(n_steps, 1);
    d_diff_arr = zeros(n_steps, 1);
    
    for i = 1:n_steps
        t = (i - 1) * Ts;
        if t >= 2.0
            plant.lead_decelerate(-3.0);
        end
        s = plant.state();
        [a_cmd, ~] = ctrl.step(s.v_ego, s.v_lead, s.d_actual, v_set);
        plant.step(a_cmd);
        ds = ctrl.d_safe(s.v_ego);
        
        t_arr(i) = t;
        d_diff_arr(i) = s.d_actual - ds;
    end
    
    mask = (t_arr >= 5.0);
    min_diff = min(d_diff_arr(mask));
    passed = (min_diff >= 0.0);
    
    res = struct(...
        'requirement_id', 'ACC-REQ-002', ...
        'passed', passed, ...
        'details', sprintf('Min (d_actual-d_safe) in [5,15]s = %.3f m (must be >= 0)', min_diff) ...
    );
end
