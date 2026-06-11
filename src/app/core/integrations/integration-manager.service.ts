import { Injectable } from '@angular/core';
import { TicketIntegration, TicketPayload, TicketResult } from './ticket-integration.interface';
import { JiraAdapter } from './jira.adapter';
import { SmaxAdapter } from './smax.adapter';

export type IntegrationProvider = 'jira' | 'smax';

@Injectable({ providedIn: 'root' })
export class IntegrationManagerService {
  private activeProvider: IntegrationProvider = 'jira';

  private readonly adapters: Record<IntegrationProvider, TicketIntegration>;

  constructor(jira: JiraAdapter, smax: SmaxAdapter) {
    this.adapters = { jira, smax };
  }

  setProvider(provider: IntegrationProvider): void {
    this.activeProvider = provider;
  }

  getProvider(): IntegrationProvider {
    return this.activeProvider;
  }

  getAdapterName(): string {
    return this.adapters[this.activeProvider].name;
  }

  async createTicket(payload: TicketPayload): Promise<TicketResult> {
    return this.adapters[this.activeProvider].createTicket(payload);
  }

  async getTicketStatus(ticketKey: string): Promise<string> {
    return this.adapters[this.activeProvider].getTicketStatus(ticketKey);
  }
}
