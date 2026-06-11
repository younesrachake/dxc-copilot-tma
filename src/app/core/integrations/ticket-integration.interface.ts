export interface TicketPayload {
  summary: string;
  description: string;
  type: string;
  priority: string;
  project: string;
  assignee: string;
}

export interface TicketResult {
  id: string;
  key: string;
  url: string;
  status: string;
  priority: string;
  createdAt: Date;
}

export interface TicketIntegration {
  readonly name: string;
  createTicket(payload: TicketPayload): Promise<TicketResult>;
  getTicketStatus(ticketKey: string): Promise<string>;
}
