import { Injectable } from '@angular/core';
import { TicketIntegration, TicketPayload, TicketResult } from './ticket-integration.interface';

@Injectable({ providedIn: 'root' })
export class SmaxAdapter implements TicketIntegration {
  readonly name = 'SMAX';

  async createTicket(payload: TicketPayload): Promise<TicketResult> {
    await this.simulateDelay(800);

    const id = `TMA-${Math.floor(Math.random() * 9000 + 1000)}`;
    return {
      id:        `smax-mock-${Date.now()}`,
      key:       id,
      url:       `https://smax.dxc.com/saw/ess/ticket/${id}`,
      status:    'Nouveau',
      priority:  payload.priority,
      createdAt: new Date()
    };
  }

  async getTicketStatus(ticketKey: string): Promise<string> {
    await this.simulateDelay(400);
    const statuses = ['Nouveau', 'En cours d\'analyse', 'En attente client', 'Résolu', 'Fermé'];
    return statuses[Math.floor(Math.random() * statuses.length)];
  }

  private simulateDelay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
