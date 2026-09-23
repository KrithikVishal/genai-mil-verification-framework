classdef PlantModel < handle
    % PlantModel
    % Longitudinal vehicle dynamics for ego + lead vehicle pair.
    
    properties
        Ts          double = 0.1
        v_ego       double = 0.0
        x_ego       double = 0.0
        v_lead      double = Inf
        x_lead      double = Inf
        lead_decel  double = 0.0
    end
    
    methods
        function obj = PlantModel(sample_time_s)
            if nargin >= 1
                obj.Ts = sample_time_s;
            end
            obj.reset();
        end
        
        function reset(obj, v_ego_init, d_init, v_lead_init, x_ego_init)
            if nargin < 2, v_ego_init = 0.0; end
            if nargin < 3, d_init = 50.0; end
            if nargin < 4, v_lead_init = Inf; end
            if nargin < 5, x_ego_init = 0.0; end
            
            obj.v_ego = double(v_ego_init);
            obj.x_ego = double(x_ego_init);
            obj.v_lead = double(v_lead_init);
            obj.x_lead = double(x_ego_init + d_init);
            obj.lead_decel = 0.0;
        end
        
        function lead_decelerate(obj, decel_mps2)
            obj.lead_decel = double(decel_mps2);
        end
        
        function s = state(obj)
            if obj.x_lead < 1e6
                d_actual = max(0.0, obj.x_lead - obj.x_ego);
            else
                d_actual = Inf;
            end
            
            s = struct(...
                'v_ego', obj.v_ego, ...
                'x_ego', obj.x_ego, ...
                'v_lead', obj.v_lead, ...
                'x_lead', obj.x_lead, ...
                'd_actual', d_actual ...
            );
        end
        
        function s = step(obj, a_cmd, v_lead_override)
            if nargin >= 3 && ~isempty(v_lead_override)
                obj.v_lead = double(v_lead_override);
            end
            
            dt = obj.Ts;
            
            % Update ego kinematics
            obj.v_ego = max(0.0, obj.v_ego + a_cmd * dt);
            obj.x_ego = obj.x_ego + obj.v_ego * dt;
            
            % Update lead kinematics
            if obj.v_lead < 1e6
                new_v_lead = max(0.0, obj.v_lead + obj.lead_decel * dt);
                obj.x_lead = obj.x_lead + obj.v_lead * dt;
                obj.v_lead = new_v_lead;
            end
            
            obj.lead_decel = 0.0; % Reset decel for next step
            s = obj.state();
        end
    end
end
