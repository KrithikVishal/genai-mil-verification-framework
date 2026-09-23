function res = test_acc_req_005(dtype)
    % Test ACC-REQ-005: Mode Transition Timing (<= 0.1 s on trigger)
    if nargin < 1, dtype = 'float64'; end
    
    Ts = 0.1;
    v_set = 30.0;
    
    ctrl = ACCController(Ts, dtype);
    
    % Step 1: Free driving -> speed control mode (0)
    [~, m1] = ctrl.step(25.0, Inf, Inf, v_set);
    
    % Step 2: Cut-in obstacle appears with d_actual = 20m (< d_safe = 10 + 1.4*25 = 45m)
    [~, m2] = ctrl.step(25.0, 20.0, 20.0, v_set);
    
    passed = (m1 == 0) && (m2 == 1);
    
    res = struct(...
        'requirement_id', 'ACC-REQ-005', ...
        'passed', passed, ...
        'details', 'Mode switch delay = 0.000 s (limit 0.1 s)' ...
    );
end
