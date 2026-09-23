function res = test_acc_req_001(dtype)
    % Test ACC-REQ-001: Speed Tracking in Steady-State (±0.5 m/s after 5s)
    if nargin < 1, dtype = 'float64'; end
    
    Ts = 0.1;
    v_set = 30.0;
    d_init = 50.0;
    T_total = 20.0;
    
    ctrl = ACCController(Ts, dtype);
    plant = PlantModel(Ts);
    plant.reset(28.0, d_init, 35.0); % Lead faster than set speed
    
    n_steps = floor(T_total / Ts);
    t_arr = zeros(n_steps, 1);
    v_ego_arr = zeros(n_steps, 1);
    
    for i = 1:n_steps
        t = (i - 1) * Ts;
        s = plant.state();
        [a_cmd, ~] = ctrl.step(s.v_ego, s.v_lead, s.d_actual, v_set);
        plant.step(a_cmd);
        
        t_arr(i) = t;
        v_ego_arr(i) = s.v_ego;
    end
    
    mask = (t_arr >= 5.0);
    max_err = max(abs(v_ego_arr(mask) - v_set));
    passed = (max_err <= 0.5);
    
    res = struct(...
        'requirement_id', 'ACC-REQ-001', ...
        'passed', passed, ...
        'details', sprintf('Max speed error in window [5,20]s = %.3f m/s (limit 0.5 m/s)', max_err) ...
    );
end
