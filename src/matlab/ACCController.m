classdef ACCController < handle
    % ACCController
    % MATLAB Model Predictive Control / Longitudinal ACC Controller
    % Matches MathWorks mpcACCsystem logic with mode arbitration.
    
    properties
        Ts          double = 0.1
        dtype       char   = 'float64'
        kp_speed    double = 0.5
        kp_space    double = 0.4
        kd_space    double = 1.2
        D_default   double = 10.0
        T_gap       double = 1.4
        a_min       double = -3.0
        a_max       double = 2.0
        mode        double = 0       % 0 = speed control, 1 = spacing control
        prev_d_error double = 0.0
    end
    
    methods
        function obj = ACCController(sample_time_s, dtype, kp_speed, kp_space, kd_space, D_default, T_gap, a_min, a_max)
            if nargin >= 1, obj.Ts = sample_time_s; end
            if nargin >= 2, obj.dtype = dtype; end
            if nargin >= 3, obj.kp_speed = kp_speed; end
            if nargin >= 4, obj.kp_space = kp_space; end
            if nargin >= 5, obj.kd_space = kd_space; end
            if nargin >= 6, obj.D_default = D_default; end
            if nargin >= 7, obj.T_gap = T_gap; end
            if nargin >= 8, obj.a_min = a_min; end
            if nargin >= 9, obj.a_max = a_max; end
            obj.reset();
        end
        
        function reset(obj)
            obj.mode = 0;
            obj.prev_d_error = 0.0;
        end
        
        function ds = d_safe(obj, v_ego)
            % Compute safe following distance per ACC-REQ-003
            v = ACCController.quantize(v_ego, obj.dtype);
            ds = ACCController.quantize(obj.D_default + obj.T_gap * v, obj.dtype);
        end
        
        function [a_cmd, mode_out] = step(obj, v_ego, v_lead, d_actual, v_set)
            % Execute one sample step of the ACC controller
            v_ego    = ACCController.quantize(v_ego, obj.dtype);
            v_lead   = ACCController.quantize(v_lead, obj.dtype);
            d_actual = ACCController.quantize(d_actual, obj.dtype);
            v_set    = ACCController.quantize(v_set, obj.dtype);
            
            ds = obj.d_safe(v_ego);
            
            % Speed tracking law
            speed_error = ACCController.quantize(v_set - v_ego, obj.dtype);
            a_speed     = ACCController.quantize(obj.kp_speed * speed_error, obj.dtype);
            
            % Spacing control law
            lead_present = (d_actual < 1e6) && (v_lead < 1e6);
            if lead_present
                d_error = ACCController.quantize(d_actual - ds, obj.dtype);
                delta_v = ACCController.quantize(v_lead - v_ego, obj.dtype);
                a_space = ACCController.quantize(obj.kp_space * d_error + obj.kd_space * delta_v, obj.dtype);
                
                % Mode arbitration (ACC-REQ-005 single-step transition)
                if (d_actual <= ds) || (a_space < a_speed)
                    obj.mode = 1; % Spacing control
                    a_cmd = a_space;
                else
                    obj.mode = 0; % Speed control
                    a_cmd = a_speed;
                end
                obj.prev_d_error = d_error;
            else
                obj.mode = 0;
                a_cmd = a_speed;
            end
            
            % Actuator saturation (ACC-REQ-004: [-3, 2] m/s^2)
            a_cmd = max(obj.a_min, min(obj.a_max, a_cmd));
            a_cmd = ACCController.quantize(a_cmd, obj.dtype);
            mode_out = obj.mode;
        end
    end
    
    methods (Static)
        function out = quantize(val, dtype)
            % Emulates hardware precision variants in MATLAB
            switch lower(dtype)
                case 'float64'
                    out = double(val);
                case 'float32'
                    out = double(single(val));
                case 'fixed16'
                    % 16-bit signed, fraction 8 bits (LSB = 2^-8 = 0.00390625)
                    q = 2^-8;
                    clamped = max(-128.0, min(127.996, val));
                    out = double(round(clamped / q) * q);
                case 'fixed8'
                    % 8-bit signed, fraction 4 bits (LSB = 2^-4 = 0.0625)
                    q = 2^-4;
                    clamped = max(-8.0, min(7.9375, val));
                    out = double(round(clamped / q) * q);
                otherwise
                    out = double(val);
            end
        end
    end
end
