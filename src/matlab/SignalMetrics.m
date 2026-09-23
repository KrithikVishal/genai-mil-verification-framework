classdef SignalMetrics
    % SignalMetrics
    % Utility functions for verification signal analysis in MATLAB
    
    methods (Static)
        function err = rms_error(a, b)
            a = double(a(:));
            b = double(b(:));
            err = sqrt(mean((a - b).^2));
        end
        
        function err = max_abs_error(a, b)
            a = double(a(:));
            b = double(b(:));
            err = max(abs(a - b));
        end
        
        function idx = divergence_index(a, b, tolerance)
            if nargin < 3, tolerance = 0.5; end
            a = double(a(:));
            b = double(b(:));
            diffs = abs(a - b);
            idx_found = find(diffs > tolerance, 1, 'first');
            if isempty(idx_found)
                idx = -1;
            else
                idx = idx_found;
            end
        end
        
        function t_div = divergence_time(time_vec, a, b, tolerance)
            if nargin < 4, tolerance = 0.5; end
            idx = SignalMetrics.divergence_index(a, b, tolerance);
            if idx == -1
                t_div = NaN;
            else
                t_div = time_vec(idx);
            end
        end
    end
end
