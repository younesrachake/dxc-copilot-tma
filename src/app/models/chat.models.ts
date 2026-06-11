import { TicketResult } from '../core/integrations/ticket-integration.interface';

export interface Artifact {
  id: string;
  type: 'python' | 'bash' | 'typescript' | 'json' | 'yaml' | 'config' | 'text';
  title: string;
  content: string;
  editMode: boolean;
  editedContent: string;
  corrected: boolean;
}

export interface TerminalCmd {
  cmd: string;
  target: string;
  status: 'idle' | 'running' | 'success' | 'error';
  output: string;
}

export interface JiraTicketDraft {
  summary: string;
  description: string;
  type: 'Bug' | 'Tâche' | 'Histoire';
  priority: 'Critique' | 'Haute' | 'Moyenne' | 'Basse';
  project: string;
  assignee: string;
  status: 'draft' | 'sending' | 'sent';
  ticketResult?: TicketResult;
}

export interface GuideCard {
  incidentType: string;
  occurrences: number;
  filename: string;
}

export interface AttachedFile {
  name: string;
  size: number;
  mimeType: string;
  kind: 'image' | 'audio' | 'document';
  preview?: string;
}

export interface ChatMessage {
  id: number;
  text: string;
  sender: 'user' | 'bot';
  timestamp: Date;
  artifact?: Artifact;
  terminalCmds?: TerminalCmd[];
  jiraTicket?: JiraTicketDraft;
  guideCard?: GuideCard;
  attachments?: AttachedFile[];
  feedback?: 'up' | 'down' | null;
  jiraTooltipOpen?: boolean;
  savedAsDocument?: boolean;
  sources?: string[];  // KB source IDs used to generate this response
}
