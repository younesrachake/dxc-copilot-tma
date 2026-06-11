import { Injectable } from '@angular/core';
import { TicketIntegration, TicketPayload, TicketResult } from './ticket-integration.interface';

@Injectable({ providedIn: 'root' })
export class JiraAdapter implements TicketIntegration {
  readonly name = 'Jira';

  async createTicket(payload: TicketPayload): Promise<TicketResult> {
    await this.simulateDelay(600);

    const key = `${payload.project}-${Math.floor(Math.random() * 9000 + 1000)}`;
    return {
      id:        `jira-mock-${Date.now()}`,
      key,
      url:       `https://dxc.atlassian.net/browse/${key}`,
      status:    'En cours d\'analyse',
      priority:  payload.priority,
      createdAt: new Date()
    };
  }

  async getTicketStatus(ticketKey: string): Promise<string> {
    await this.simulateDelay(300);
    const statuses = ['En cours d\'analyse', 'En cours', 'En attente de validation', 'Résolu'];
    return statuses[Math.floor(Math.random() * statuses.length)];
  }

  private simulateDelay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
