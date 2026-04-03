// Based on the Pydantic model in the backend

export interface ActionSettings {
  enabled: boolean;
  primary_action: 'auto' | 'send_message' | 'create_order_candidate';
  message_template_id: 'auto' | 'ask_availability' | 'ask_condition' | 'ask_battery' | 'ask_lowest_price';
  min_ai_score: number;
  seller_cooldown_seconds: number;
  order_candidate_score_threshold: number;
  risk_words: string[];
}

export interface VehicleFilter {
  series?: string[];
  variant_keywords?: string[];
  mileage_km_min?: number;
  mileage_km_max?: number;
  transfer_count?: number;
  locations?: string[];
  register_month_start?: string;
  register_month_end?: string;
}

export interface Task {
  id: number;
  task_name: string;
  enabled: boolean;
  keyword: string;
  description: string;
  analyze_images: boolean;
  max_pages: number;
  personal_only: boolean;
  min_price: string | null;
  max_price: string | null;
  cron: string | null;
  next_run_at?: string | null;
  ai_prompt_base_file: string;
  ai_prompt_criteria_file: string;
  account_state_file?: string | null;
  account_strategy: 'auto' | 'fixed' | 'rotate';
  free_shipping?: boolean;
  new_publish_option?: string | null;
  region?: string | null;
  decision_mode: 'ai' | 'keyword';
  keyword_rules: string[];
  action_settings: ActionSettings;
  enable_structured_prefilter: boolean;
  vehicle_filter: VehicleFilter;
  is_running: boolean;
}

export type TaskGenerationStatus = 'queued' | 'running' | 'completed' | 'failed';
export type TaskGenerationStepStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface TaskGenerationStep {
  key: string;
  label: string;
  status: TaskGenerationStepStatus;
  message: string;
}

export interface TaskGenerationJob {
  job_id: string;
  task_name: string;
  status: TaskGenerationStatus;
  message: string;
  current_step: string | null;
  steps: TaskGenerationStep[];
  task: Task | null;
  error: string | null;
}

export interface TaskCreateResponse {
  message: string;
  task?: Task;
  job?: TaskGenerationJob;
}

// For PATCH requests, all fields are optional
export type TaskUpdate = Partial<Omit<Task, 'id' | 'next_run_at'>>;

// For task creation
export interface TaskGenerateRequest {
  task_name: string;
  keyword: string;
  description?: string;
  analyze_images?: boolean;
  personal_only?: boolean;
  min_price?: string | null;
  max_price?: string | null;
  max_pages?: number;
  cron?: string | null;
  account_state_file?: string | null;
  account_strategy?: 'auto' | 'fixed' | 'rotate';
  free_shipping?: boolean;
  new_publish_option?: string | null;
  region?: string | null;
  decision_mode?: 'ai' | 'keyword';
  keyword_rules?: string[];
  action_settings?: ActionSettings;
  enable_structured_prefilter?: boolean;
  vehicle_filter?: VehicleFilter;
}
