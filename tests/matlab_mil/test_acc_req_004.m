function res = test_acc_req_004(dtype)
    % Test ACC-REQ-004: Acceleration Command Limits ([-3, 2] m/s^2)
    if nargin < 1, dtype = 'float64'; end
    
    Ts = 0.1;
    v_set = 30.0;
    d_init = 40.0;
    T_total = 20.0;
    
    ctrl = ACCController(Ts, dtype);
    plant = PlantModel(Ts);
    plant.reset(30.0, d_init, 30.0);
    
    n_steps = floor(T_total / Ts);
    a_cmd_arr = zeros(n_steps, 1);
    
    for i = 1:n_steps
        t = (i - 1) * Ts;
        if t >= 3.0
            plant.lead_decelerate(-5.0);
        end
        s = plant.state();
        [a_cmd, ~] = ctrl.step(s.v_ego, s.v_lead, s.d_actual, v_set);
        plant.step(a_cmd);
        a_cmd_arr(i) = a_cmd;
    end
    
    min_a = min(a_cmd_arr);
    max_a = max(a_cmd_arr);
    passed = (min_a >= -3.001) && (max_a <= 2.001);
    
    res = struct(...
        'requirement_id', 'ACC-REQ-004', ...
        'passed', passed, ...
        'details', sprintf('a_cmd range: [%.3f, %.3f] m/s^2 (limit [-3, 2] m/s^2)', min_a, max_a) ...
    );
end
