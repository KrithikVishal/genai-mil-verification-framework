function res = test_acc_req_003(dtype)
    % Test ACC-REQ-003: Safe Following Distance Formula (D_safe = 10 + 1.4*v_ego)
    if nargin < 1, dtype = 'float64'; end
    
    Ts = 0.1;
    v_set = 25.0;
    d_init = 60.0;
    T_total = 10.0;
    
    ctrl = ACCController(Ts, dtype);
    plant = PlantModel(Ts);
    plant.reset(25.0, d_init, 30.0);
    
    n_steps = floor(T_total / Ts);
    errs = zeros(n_steps, 1);
    
    for i = 1:n_steps
        s = plant.state();
        [a_cmd, ~] = ctrl.step(s.v_ego, s.v_lead, s.d_actual, v_set);
        plant.step(a_cmd);
        ds_actual = ctrl.d_safe(s.v_ego);
        ds_expected = 10.0 + 1.4 * s.v_ego;
        errs(i) = abs(ds_actual - ds_expected);
    end
    
    max_formula_err = max(errs);
    passed = (max_formula_err < 1e-4);
    
    res = struct(...
        'requirement_id', 'ACC-REQ-003', ...
        'passed', passed, ...
        'details', sprintf('Max D_safe formula error = %.2e m', max_formula_err) ...
    );
end
