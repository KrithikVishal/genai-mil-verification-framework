function results = run_all_mil_tests(dtype)
    % run_all_mil_tests
    % Master test suite runner for MIL requirements in MATLAB
    if nargin < 1, dtype = 'float64'; end
    
    here = fileparts(mfilename('fullpath'));
    root_dir = fileparts(fileparts(here));
    addpath(fullfile(root_dir, 'src', 'matlab'));
    addpath(here);
    
    fprintf('\n=== MATLAB MIL Test Suite  [dtype=%s] ===\n\n', dtype);
    
    test_funcs = {@test_acc_req_001, @test_acc_req_002, @test_acc_req_003, @test_acc_req_004, @test_acc_req_005};
    results = cell(length(test_funcs), 1);
    
    passed_count = 0;
    fprintf('%-15s %-10s  %s\n', 'Req ID', 'Result', 'Details');
    fprintf('%s\n', repmat('-', 1, 70));
    
    for i = 1:length(test_funcs)
        fn = test_funcs{i};
        r = fn(dtype);
        results{i} = r;
        
        if r.passed
            status = 'PASS';
            passed_count = passed_count + 1;
        else
            status = 'FAIL';
        end
        fprintf('  %-13s %-10s  %s\n', r.requirement_id, status, r.details);
    end
    
    fprintf('%s\n', repmat('-', 1, 70));
    fprintf('  %d/%d passed\n\n', passed_count, length(test_funcs));
end
