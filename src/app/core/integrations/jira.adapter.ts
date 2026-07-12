import { Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { TicketIntegration, TicketPayload, TicketResult } from './ticket-integration.interface';
import { ApiService } from '../../services/api.service';

@Injectable({ providedIn: 'root' })
export class JiraAdapter implements TicketIntegration {
  readonly name = 'Jira';

  constructor(private api: ApiService) {}

  async createTicket(payload: TicketPayload): Promise<TicketResult> {
    // The backend stores summary/description/priority — fold the rest into the description
    const description =
      `${payload.description}\n\n` +
      `Projet : ${payload.project} | Type : ${payload.type} | Assigné à : ${payload.assignee}`;
    const res = await firstValueFrom(
      this.api.createJiraTicket(payload.summary, description, payload.priority)
    );
    return {
      id:        res.key,
      key:       res.key,
      url:       res.url || `https://jira.dxc.com/browse/${res.key}`,
      status:    res.status || 'Created',
      priority:  payload.priority,
      createdAt: new Date()
    };
  }

  async getTicketStatus(ticketKey: string): Promise<string> {
    const res = await firstValueFrom(this.api.getJiraStatus(ticketKey));
    return res.status;
  }
}
