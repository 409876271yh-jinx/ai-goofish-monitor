export type ActionType = 'send_message' | 'create_order_candidate' | 'skip';
export type ActionStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled';

export interface ActionSummary {
  task_name: string;
  title: string;
  price: string;
  link: string;
  reason: string;
  risk_tags: string[];
  template_id?: string | null;
  executor_status?: string | null;
}

export interface ActionRecord {
  id: number;
  task_id?: number | null;
  item_id: string;
  seller_id?: string | null;
  action_type: ActionType;
  status: ActionStatus;
  payload: Record<string, unknown>;
  idempotency_key: string;
  retry_count: number;
  last_error: string;
  created_at: string;
  updated_at: string;
  summary: ActionSummary;
}
