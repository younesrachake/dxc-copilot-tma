import { Component, ElementRef, ViewChild, AfterViewChecked, OnInit, OnDestroy, ChangeDetectorRef } from '@angular/core';
import { NgFor, NgIf, DatePipe, SlicePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { IntegrationManagerService } from '../core/integrations/integration-manager.service';
import { ChatStoreService } from '../services/chat-store.service';
import { ApiService } from '../services/api.service';
import { DocumentStoreService } from '../services/document-store.service';
import { Artifact, TerminalCmd, JiraTicketDraft, ChatMessage, AttachedFile, GuideCard } from '../models/chat.models';
import { IconComponent } from '../shared/icon.component';
import { MarkdownLitePipe } from '../shared/markdown.pipe';
import { TtsService } from '../services/tts.service';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule, DatePipe, SlicePipe, IconComponent, MarkdownLitePipe],
  templateUrl: './chat.component.html',
  styleUrl: './chat.component.scss'
})
export class ChatComponent implements OnInit, AfterViewChecked, OnDestroy {
  @ViewChild('messagesEnd') messagesEnd!: ElementRef;
  @ViewChild('fileInput')  fileInputRef!: ElementRef<HTMLInputElement>;
  @ViewChild('audioInput') audioInputRef!: ElementRef<HTMLInputElement>;
  private shouldScroll = false;

  messages: ChatMessage[] = [];
  showWelcome = true;

  readonly suggestions = [
    { iconName: 'activity', text: 'Analyser les logs de l\'API Gateway et identifier les erreurs critiques.' },
    { iconName: 'code',     text: 'Écrire un script Python pour surveiller la consommation mémoire des serveurs.' },
    { iconName: 'zap',      text: 'Comment redémarrer proprement le service nginx en production ?' },
    { iconName: 'ticket',   text: 'Créer un ticket Jira pour un incident critique sur l\'infrastructure.' }
  ];

  newMessage = '';
  isLoading = false;

  // ── Canvas / Artifacts ──────────────────────────────────────────
  canvasOpen = false;
  activeArtifact: Artifact | null = null;
  copied = false;

  // ── Streaming / Typing Effect ────────────────────────────────────
  streamingIds = new Set<number>();
  displayedTexts = new Map<number, string>();

  // ── Terminal line-by-line ────────────────────────────────────────
  terminalLines = new Map<string, string[]>();

  // ── Terminal Drawer ──────────────────────────────────────────────
  showTerminalDrawer = false;
  drawerCmds: TerminalCmd[] = [];

  openTerminalDrawer(cmds: TerminalCmd[]): void {
    this.drawerCmds = cmds;
    this.showTerminalDrawer = true;
  }

  closeTerminalDrawer(): void {
    this.showTerminalDrawer = false;
  }

  // ── Jira Modal ───────────────────────────────────────────────────
  showJiraModal = false;
  jiraModalMsgId: number | null = null;
  jiraModalTicket: import('../models/chat.models').JiraTicketDraft | null = null;

  openJiraModal(ticket: import('../models/chat.models').JiraTicketDraft, msgId: number): void {
    this.jiraModalTicket = ticket;
    this.jiraModalMsgId = msgId;
    this.showJiraModal = true;
  }

  closeJiraModal(): void {
    this.showJiraModal = false;
    this.jiraModalTicket = null;
    this.jiraModalMsgId = null;
  }

  confirmJiraModal(): void {
    if (!this.jiraModalTicket || this.jiraModalMsgId === null) return;
    this.confirmJiraTicket(this.jiraModalTicket, this.jiraModalMsgId);
    this.closeJiraModal();
  }

  // ── Micro-interaction states ─────────────────────────────────────
  thumbsUpFlash = new Set<number>();   // msg ids flashing green
  jiraSuccess   = new Set<number>();   // msg ids with jira success anim

  // ── RLHF Feedback Modal ─────────────────────────────────────────
  showFeedbackModal = false;
  feedbackTargetId: number | null = null;
  feedbackReason = '';
  selectedFeedbackOption = '';
  feedbackSubmitting = false;
  feedbackOptions = [
    'Réponse incorrecte',
    'Code avec erreur',
    'Réponse incomplète',
    'Hors sujet',
    'Autre'
  ];

  // ── Voice Recording ──────────────────────────────────────────
  isRecording = false;
  private recognition: any = null;

  // ── Persistent Guide Card (survives chat switches) ──────────────
  persistentGuideCard: GuideCard | null = null;

  dismissGuideCard(): void {
    this.persistentGuideCard = null;
  }

  // ── Multimodal Attachments ────────────────────────────────────
  attachments: AttachedFile[] = [];
  errorNotification: string | null = null;
  loadingText = '';

  // ── Validation constants (RG1 / RG3) ─────────────────────────
  private readonly MAX_MSG_LENGTH = 4000;
  private readonly MAX_TOTAL_MB = 15;
  private readonly ALLOWED_MIME = new Set([
    'image/png', 'image/jpeg',
    'application/pdf', 'text/plain',
    'audio/wav', 'audio/mpeg', 'audio/mp3'
  ]);
  private readonly ALLOWED_EXT = new Set(['.png','.jpg','.jpeg','.pdf','.txt','.wav','.mp3']);
  private timeoutHandle: ReturnType<typeof setTimeout> | null = null;
  private currentSessionId: string | undefined;
  private pendingFile: File | null = null;
  // Track all active streaming intervals to clean up on destroy
  private activeIntervals = new Set<ReturnType<typeof setInterval>>();
  // Flag for stop button
  isCancelling = false;

  // ── Follow-up suggestion chips (cleared on each new message) ──
  followups: string[] = [];

  constructor(
    private router: Router,
    public integrationManager: IntegrationManagerService,
    private chatStore: ChatStoreService,
    private api: ApiService,
    private cdr: ChangeDetectorRef,
    private documentStore: DocumentStoreService,
    public tts: TtsService
  ) {}

  // ── Text-to-speech ────────────────────────────────────────────
  toggleSpeak(msg: ChatMessage): void {
    if (this.tts.isSpeaking(msg.id)) {
      this.tts.stop();
    } else {
      this.tts.speak(msg.text, msg.id, () => this.cdr.detectChanges());
    }
  }

  // ── Export conversation as Markdown ───────────────────────────
  exportConversation(): void {
    if (!this.messages.length) return;
    const lines: string[] = [
      `# Conversation DXC Copilot`,
      `_Exportée le ${new Date().toLocaleString('fr-FR')}_`,
      '',
    ];
    for (const m of this.messages) {
      lines.push(m.sender === 'user' ? '**Vous :**' : '**Copilot :**');
      lines.push(m.text, '');
      if (m.sources?.length) lines.push(`> Sources KB : ${m.sources.join(', ')}`, '');
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `conversation-${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  useFollowup(text: string): void {
    this.followups = [];
    this.newMessage = text;
    this.sendMessage();
  }

  toggleSteps(msg: ChatMessage): void {
    msg.stepsCollapsed = !msg.stepsCollapsed;
  }

  ngOnInit(): void {
    this.chatStore.activeChatId$.subscribe(id => {
      if (id === 0) {
        // New chat — clear messages
        this.messages = [];
        this.showWelcome = true;
        this.currentSessionId = undefined;
        this.displayedTexts.clear();
        this.streamingIds.clear();
        this.shouldScroll = true;
      }
    });
    this.chatStore.activeBackendSessionId$.subscribe(sid => {
      if (sid) this.loadBackendSession(sid);
    });
  }

  private loadBackendSession(sessionId: string): void {
    this.isLoading = true;
    this.currentSessionId = sessionId;
    this.api.getSessionMessages(sessionId).subscribe({
      next: (msgs) => {
        this.messages = msgs.map(m => ({
          id: m.id,
          text: m.text,
          sender: m.sender as 'user' | 'bot',
          timestamp: new Date(m.created_at),
          feedback: m.feedback as 'up' | 'down' | null | undefined
        }));
        this.showWelcome = this.messages.length === 0;
        this.displayedTexts.clear();
        this.streamingIds.clear();
        this.isLoading = false;
        this.shouldScroll = true;
      },
      error: () => {
        this.messages = [];
        this.showWelcome = true;
        this.isLoading = false;
        this.shouldScroll = true;
      }
    });
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll) {
      this.scrollToBottom();
      this.shouldScroll = false;
    }
  }

  private scrollToBottom(): void {
    try {
      this.messagesEnd?.nativeElement?.scrollIntoView({ behavior: 'smooth' });
    } catch {}
  }

  // ── Canvas ──────────────────────────────────────────────────────
  openArtifact(artifact: Artifact): void {
    this.activeArtifact = artifact;
    this.canvasOpen = true;
  }

  closeCanvas(): void {
    this.canvasOpen = false;
    setTimeout(() => { this.activeArtifact = null; }, 300);
  }

  toggleCanvas(): void {
    if (this.canvasOpen) {
      this.closeCanvas();
    } else if (this.activeArtifact) {
      this.canvasOpen = true;
    }
  }

  copyArtifact(): void {
    const content = this.activeArtifact?.editMode
      ? this.activeArtifact.editedContent
      : this.activeArtifact?.content || '';
    navigator.clipboard.writeText(content).then(() => {
      this.copied = true;
      setTimeout(() => this.copied = false, 2000);
    });
  }

  toggleEditArtifact(): void {
    if (!this.activeArtifact) return;
    if (!this.activeArtifact.editMode) {
      this.activeArtifact.editedContent = this.activeArtifact.content;
    }
    this.activeArtifact.editMode = !this.activeArtifact.editMode;
  }

  saveArtifactEdit(): void {
    if (!this.activeArtifact) return;
    this.activeArtifact.content = this.activeArtifact.editedContent;
    this.activeArtifact.editMode = false;
  }

  learnFromCorrection(): void {
    if (!this.activeArtifact) return;
    this.activeArtifact.corrected = true;
    this.activeArtifact.editMode = false;
    this.activeArtifact.content = this.activeArtifact.editedContent;
    const reason = `Correction artifact: ${this.activeArtifact.title} — ${this.activeArtifact.content.substring(0, 200)}`;
    this.api.submitFeedback(0, 'correction', reason).subscribe();
    this.errorNotification = '✅ Correction sauvegardée. L\'IA apprendra de cette amélioration.';
    setTimeout(() => { this.errorNotification = null; }, 4000);
  }

  langLabel(type: string): string {
    const map: Record<string, string> = {
      python: 'Python', bash: 'Bash', typescript: 'TypeScript',
      json: 'JSON', yaml: 'YAML', config: 'Config', text: 'Text'
    };
    return map[type] || type;
  }

  // ── Code-block extraction (Canvas) ──────────────────────────────
  private parseCodeBlocks(raw: string): { cleanText: string; artifact: Artifact | null } {
    // Matches: ```lang\ncode``` or ```\ncode```
    const re = /```(\w*)\n?([\s\S]*?)```/g;
    let artifact: Artifact | null = null;
    let blockIdx = 0;

    const cleanText = raw.replace(re, (_full, lang: string, code: string) => {
      if (blockIdx === 0) {
        const type = this.mapLangToArtifactType(lang);
        artifact = {
          id: `art-${Date.now()}`,
          type,
          title: this.defaultFilename(type),
          content: code.trim(),
          editMode: false,
          editedContent: '',
          corrected: false
        };
      }
      blockIdx++;
      return ''; // Remove code block from chat text
    }).replace(/\n{3,}/g, '\n\n').trim();

    return { cleanText, artifact };
  }

  private mapLangToArtifactType(lang: string): Artifact['type'] {
    const m: Record<string, Artifact['type']> = {
      python: 'python', py: 'python',
      bash: 'bash', sh: 'bash', shell: 'bash',
      typescript: 'typescript', ts: 'typescript',
      json: 'json',
      yaml: 'yaml', yml: 'yaml',
    };
    return m[(lang || '').toLowerCase()] ?? 'text';
  }

  private defaultFilename(type: Artifact['type']): string {
    const m: Record<string, string> = {
      python: 'solution.py', bash: 'solution.sh', typescript: 'solution.ts',
      json: 'data.json', yaml: 'config.yaml', config: 'config.conf', text: 'note.md'
    };
    return m[type] || 'code.txt';
  }

  // ── Terminal ────────────────────────────────────────────────────
  getTerminalLines(cmd: TerminalCmd): string[] {
    return this.terminalLines.get(cmd.cmd) ?? [];
  }

  executeCommand(cmd: TerminalCmd): void {
    cmd.status = 'running';
    cmd.output = '';
    this.terminalLines.set(cmd.cmd, []);

    this.api.executeTerminalCommand(cmd.cmd).subscribe({
      next: (res) => {
        this.streamTerminalOutput(cmd, res.output, res.exit_code !== 0 ? 'error' : 'success');
      },
      error: (err) => {
        const detail = err?.error?.detail || err?.message || 'Commande non autorisée ou terminal désactivé.';
        this.streamTerminalOutput(cmd, `Erreur: ${detail}`, 'error');
      }
    });
  }

  private streamTerminalOutput(cmd: TerminalCmd, fullOutput: string, finalStatus: 'success' | 'error'): void {
    const lines = fullOutput.split('\n');
    lines.forEach((line, i) => {
      setTimeout(() => {
        const current = this.terminalLines.get(cmd.cmd) ?? [];
        this.terminalLines.set(cmd.cmd, [...current, line]);
        if (i === lines.length - 1) {
          cmd.status = finalStatus;
          cmd.output = fullOutput;
        }
      }, 300 + i * 100);
    });
  }

  private simulateCommand(cmd: TerminalCmd): string {
    const c = cmd.cmd;
    if (c.includes('nginx -t')) return 'nginx: the configuration file /etc/nginx/nginx.conf syntax is ok\nnginx: configuration file /etc/nginx/nginx.conf test is successful';
    if (c.includes('reload') || c.includes('restart')) return 'Stopping service...\nFlushing buffers...\nStarting service...\nService reloaded successfully.';
    if (c.includes('systemctl status')) return `● nginx.service - A high performance web server\n   Active: active (running) since ${new Date().toLocaleString('fr-FR')}\n   Memory: 6.4M`;
    if (c.includes('is-active')) return 'active';
    if (c.includes('docker pull')) return 'Using default tag: latest\nStatus: Image is up to date';
    if (c.includes('docker-compose')) return 'Recreating dxc_api_1 ... done\napi_1  | Server listening on :8080\napi_1  | Health check passed ✓';
    if (c.includes('curl') && c.includes('health')) return '{"status":"healthy","version":"2.1.0","db":"connected"}';
    if (c.includes('top') || c.includes('ps aux')) return 'PID   USER  %CPU  %MEM  COMMAND\n 2841 dxc   87.3  92.1  api-gateway\n 2842 dxc    4.2   5.4  node';
    if (c.includes('netstat') || c.includes('ss -')) return 'tcp  0.0.0.0:8080  LISTEN\ntcp  prod-server-01:8080  ESTABLISHED\n... 843 more ESTABLISHED connections';
    if (c.includes('tail') || (c.includes('cat') && c.includes('log'))) return '[ERROR] Connection pool exhausted (max=200, active=847)\n[WARN]  Slow query detected: 8431ms\n[ERROR] OutOfMemoryError: heap space (used: 892MB / 1024MB)';
    if (c.includes('psql') && c.includes('EXPLAIN')) return 'Seq Scan on incidents  (cost=0.00..189432.00 rows=2347821)\nExecution Time: 44871.2 ms\n⚠ WARNING: Sequential scan on 2.3M rows';
    if (c.includes('psql') && c.includes('pg_indexes')) return 'schemaname | tablename | indexname\npublic     | incidents | incidents_pkey\n(1 row) — No composite indexes found!';
    return `Connecting to ${cmd.target}...\nAuthentication OK\nCommand executed successfully.`;
  }

  // ── RLHF Feedback ───────────────────────────────────────────────
  giveFeedback(msg: ChatMessage, type: 'up' | 'down'): void {
    if (msg.feedback) return;
    if (type === 'up') {
      msg.feedback = 'up';
      this.thumbsUpFlash.add(msg.id);
      setTimeout(() => this.thumbsUpFlash.delete(msg.id), 600);
      this.api.submitFeedback(msg.id, 'up').subscribe();
    } else {
      this.feedbackTargetId = msg.id;
      this.feedbackReason = '';
      this.selectedFeedbackOption = '';
      this.showFeedbackModal = true;
    }
  }

  selectFeedbackOption(opt: string): void {
    this.selectedFeedbackOption = opt;
  }

  submitFeedback(): void {
    if (this.feedbackSubmitting) return;
    const msg = this.messages.find(m => m.id === this.feedbackTargetId);
    if (msg) {
      msg.feedback = 'down';
      const reason = this.selectedFeedbackOption
        ? `${this.selectedFeedbackOption}${this.feedbackReason ? ': ' + this.feedbackReason : ''}`
        : this.feedbackReason;
      this.feedbackSubmitting = true;
      this.api.submitFeedback(msg.id, 'down', reason || undefined).subscribe({
        next: () => { this.feedbackSubmitting = false; },
        error: () => { this.feedbackSubmitting = false; }
      });
    }
    this.showFeedbackModal = false;
    this.feedbackTargetId = null;
  }

  closeFeedbackModal(): void {
    this.showFeedbackModal = false;
    this.feedbackTargetId = null;
  }

  // ── Jira ────────────────────────────────────────────────────────
  confirmJiraTicket(ticket: JiraTicketDraft, msgId: number): void {
    ticket.status = 'sending';
    this.integrationManager.createTicket({
      summary:     ticket.summary,
      description: ticket.description,
      type:        ticket.type,
      priority:    ticket.priority,
      project:     ticket.project,
      assignee:    ticket.assignee
    }).then(result => {
      ticket.status       = 'sent';
      ticket.ticketResult = result;
      this.jiraSuccess.add(msgId);
      setTimeout(() => this.jiraSuccess.delete(msgId), 1200);
    }).catch(() => {
      ticket.status = 'draft'; // Revert on failure
      this.showError('Échec de la création du ticket Jira. Vérifiez la configuration et réessayez.');
    });
  }

  toggleJiraTooltip(msg: ChatMessage): void {
    msg.jiraTooltipOpen = !msg.jiraTooltipOpen;
  }

  // ── Send ────────────────────────────────────────────────────────
  getDisplayText(msg: ChatMessage): string {
    if (msg.sender === 'user') return msg.text;
    return this.displayedTexts.has(msg.id) ? this.displayedTexts.get(msg.id)! : msg.text;
  }

  isStreaming(id: number): boolean {
    return this.streamingIds.has(id);
  }

  private streamText(msg: ChatMessage): void {
    const full = msg.text;
    const speed = 10; // ms per character
    let i = 0;
    this.streamingIds.add(msg.id);
    this.displayedTexts.set(msg.id, '');
    const interval = setInterval(() => {
      i += 3; // stream 3 chars per tick for speed
      this.displayedTexts.set(msg.id, full.substring(0, i));
      this.shouldScroll = true;
      if (i >= full.length) {
        this.displayedTexts.set(msg.id, full);
        this.streamingIds.delete(msg.id);
        clearInterval(interval);
        this.activeIntervals.delete(interval);
        if (msg.artifact) this.openArtifact(msg.artifact);
      }
    }, speed);
    this.activeIntervals.add(interval);
  }

  cancelStream(): void {
    // Stop all active streaming animations
    this.activeIntervals.forEach(i => clearInterval(i));
    this.activeIntervals.clear();
    // Finalize all partial texts to their full content
    this.streamingIds.forEach(id => {
      const msg = this.messages.find(m => m.id === id);
      if (msg) this.displayedTexts.set(id, msg.text);
    });
    this.streamingIds.clear();
    this.isLoading = false;
    this.loadingText = '';
    if (this.timeoutHandle) { clearTimeout(this.timeoutHandle); this.timeoutHandle = null; }
  }

  sendMessage(): void {
    const text = this.newMessage.trim();
    if ((!text && this.attachments.length === 0) || this.isLoading) return;
    if (text.length > this.MAX_MSG_LENGTH) {
      this.showError(`ERR — Le message dépasse la limite de ${this.MAX_MSG_LENGTH} caractères (${text.length}/${this.MAX_MSG_LENGTH}).`);
      return;
    }
    this.errorNotification = null;
    this.followups = [];
    this.tts.stop();

    this.showWelcome = false;
    const userMsg: ChatMessage = {
      id: this.messages.length + 1,
      text: text || '📎 Pièces jointes envoyées',
      sender: 'user',
      timestamp: new Date(),
      attachments: this.attachments.length ? [...this.attachments] : undefined
    };
    this.messages.push(userMsg);
    this.newMessage = '';
    this.attachments = [];
    this.isLoading = true;
    this.shouldScroll = true;

    // ── Dynamic loader text (step 1 → step 2) ─────────────────
    this.loadingText = 'Analyse des pièces jointes en cours...';
    setTimeout(() => { if (this.isLoading && !this.loadingText.startsWith('Recherche')) this.loadingText = 'Recherche dans la base de connaissances...'; }, 2000);

    // ── ERR3 — 45s timeout ─────────────────────────────────────
    this.timeoutHandle = setTimeout(() => {
      if (!this.isLoading) return;
      this.isLoading = false;
      this.loadingText = '';
      const errMsg: ChatMessage = {
        id: this.messages.length + 1,
        text: '⚠️ Le service d\'analyse est momentanément surchargé. Veuillez réessayer dans quelques instants.',
        sender: 'bot', timestamp: new Date(), feedback: null
      };
      this.messages.push(errMsg);
      this.shouldScroll = true;
    }, 45000);

    const prevSessionId = this.currentSessionId;

    // ── Streaming path (SSE) — text-only messages ─────────────
    if (!this.pendingFile) {
      this.sendViaStream(text, prevSessionId);
      return;
    }

    // ── Real HTTP call to backend API (file uploads) ──────────
    this.api.sendMessage(text || '', this.currentSessionId, this.pendingFile ?? undefined)
      .subscribe({
        next: (res) => {
          if (this.timeoutHandle) { clearTimeout(this.timeoutHandle); this.timeoutHandle = null; }
          this.currentSessionId = res.session_id;
          if (!prevSessionId && res.session_id) {
            this.chatStore.emitSessionCreated(res.session_id, text.substring(0, 50) || 'Nouveau chat');
          }
          if (res.session_title && res.session_id) {
            this.chatStore.emitSessionRenamed(res.session_id, res.session_title);
          }
          const { cleanText, artifact } = this.parseCodeBlocks(res.reply);
          const bot: ChatMessage = {
            id: this.messages.length + 1,
            text: cleanText || res.reply,
            sender: 'bot',
            timestamp: new Date(),
            feedback: null
          };
          if (artifact) bot.artifact = artifact;
          // Use backend-authoritative guide_card (RG2 tracked server-side)
          if (res.guide_card) {
            bot.guideCard = res.guide_card;
            this.persistentGuideCard = res.guide_card;
          }
          // Attach KB sources for attribution display
          if (res.sources?.length) bot.sources = res.sources;
          if (res.citations?.length) bot.citations = res.citations;
          if (res.grounded !== undefined && res.grounded !== null) bot.grounded = res.grounded;
          if (res.cached) bot.cached = true;
          // Backend-detected Jira intent → attach pre-filled draft (opens the Jira modal)
          if (res.jira_ticket) {
            bot.jiraTicket = {
              summary:     res.jira_ticket.summary || '',
              description: res.jira_ticket.description || '',
              type:        res.jira_ticket.type || 'Incident',
              priority:    res.jira_ticket.priority || 'Haute',
              project:     res.jira_ticket.project || 'TMA',
              assignee:    res.jira_ticket.assignee || '',
              status:      'draft'
            };
          }
          this.messages.push(bot);
          this.isLoading = false;
          this.loadingText = '';
          this.shouldScroll = true;
          this.streamText(bot);
          this.pendingFile = null;
        },
        error: (err) => {
          if (this.timeoutHandle) { clearTimeout(this.timeoutHandle); this.timeoutHandle = null; }
          const errMsg: ChatMessage = {
            id: this.messages.length + 1,
            text: `⚠️ ${err.message || 'Erreur de communication avec le serveur.'}`,
            sender: 'bot',
            timestamp: new Date(),
            feedback: null
          };
          this.messages.push(errMsg);
          this.isLoading = false;
          this.loadingText = '';
          this.shouldScroll = true;
          this.pendingFile = null;
        }
      });
  }

  // ── Real token streaming over SSE ────────────────────────────────
  private sendViaStream(text: string, prevSessionId?: string): void {
    const bot: ChatMessage = {
      id: this.messages.length + 1,
      text: '',
      sender: 'bot',
      timestamp: new Date(),
      feedback: null
    };
    let botPushed = false;

    const clearTimer = () => {
      if (this.timeoutHandle) { clearTimeout(this.timeoutHandle); this.timeoutHandle = null; }
    };

    this.followups = [];
    this.api.streamMessage(text, this.currentSessionId, {
      onStatus: (s) => {
        this.loadingText = s;
        this.cdr.detectChanges();
      },
      onAgentStep: (step) => {
        clearTimer();
        if (!botPushed) {
          botPushed = true;
          this.isLoading = false;
          this.loadingText = '';
          this.messages.push(bot);
          this.streamingIds.add(bot.id);
        }
        bot.agentSteps = bot.agentSteps || [];
        // previous step finishes when the next one starts
        bot.agentSteps.forEach(s => s.done = true);
        bot.agentSteps.push({ tool: step.tool, label: step.label, done: false });
        this.shouldScroll = true;
        this.cdr.detectChanges();
      },
      onToken: (t) => {
        clearTimer();
        if (!botPushed) {
          botPushed = true;
          this.isLoading = false;
          this.loadingText = '';
          this.messages.push(bot);
          this.streamingIds.add(bot.id);
        }
        if (bot.agentSteps) {
          // answer started → all steps complete, collapse the timeline
          bot.agentSteps.forEach(s => s.done = true);
          if (bot.stepsCollapsed === undefined) bot.stepsCollapsed = true;
        }
        bot.text += t;
        this.displayedTexts.set(bot.id, bot.text);
        this.shouldScroll = true;
        this.cdr.detectChanges();
      },
      onFollowups: (items) => {
        this.followups = items;
        this.shouldScroll = true;
        this.cdr.detectChanges();
      },
      onMeta: (meta) => {
        if (meta.session_id) {
          this.currentSessionId = meta.session_id;
          if (!prevSessionId) {
            this.chatStore.emitSessionCreated(meta.session_id, text.substring(0, 50) || 'Nouveau chat');
          }
          if (meta.session_title) {
            this.chatStore.emitSessionRenamed(meta.session_id, meta.session_title);
          }
        }
        if (meta.guide_card) {
          bot.guideCard = meta.guide_card;
          this.persistentGuideCard = meta.guide_card;
        }
        if (meta.sources?.length) bot.sources = meta.sources;
        if (meta.citations?.length) bot.citations = meta.citations;
        if (meta.grounded !== undefined && meta.grounded !== null) bot.grounded = meta.grounded;
        if (meta.cached) bot.cached = true;
        if (meta.jira_ticket) {
          bot.jiraTicket = {
            summary:     meta.jira_ticket.summary || '',
            description: meta.jira_ticket.description || '',
            type:        meta.jira_ticket.type || 'Incident',
            priority:    meta.jira_ticket.priority || 'Haute',
            project:     meta.jira_ticket.project || 'TMA',
            assignee:    meta.jira_ticket.assignee || '',
            status:      'draft'
          };
        }
        this.cdr.detectChanges();
      },
      onDone: () => {
        clearTimer();
        this.streamingIds.delete(bot.id);
        if (botPushed) {
          const { cleanText, artifact } = this.parseCodeBlocks(bot.text);
          if (artifact) {
            bot.artifact = artifact;
            bot.text = cleanText || bot.text;
            this.openArtifact(artifact);
          }
          this.displayedTexts.set(bot.id, bot.text);
        }
        this.isLoading = false;
        this.loadingText = '';
        this.shouldScroll = true;
        this.cdr.detectChanges();
      },
      onError: (message) => {
        clearTimer();
        this.streamingIds.delete(bot.id);
        if (!botPushed) {
          this.messages.push({
            id: this.messages.length + 1,
            text: `⚠️ ${message}`,
            sender: 'bot', timestamp: new Date(), feedback: null
          });
        } else {
          bot.text += `\n\n⚠️ ${message}`;
          this.displayedTexts.set(bot.id, bot.text);
        }
        this.isLoading = false;
        this.loadingText = '';
        this.shouldScroll = true;
        this.cdr.detectChanges();
      }
    });
  }

  private generateBotResponse(userText: string, id: number): ChatMessage {
    const lower = userText.toLowerCase();
    const now = new Date();

    if (lower.includes('jira') || lower.includes('ticket') ||
        (lower.includes('créer') && (lower.includes('bug') || lower.includes('issue')))) {
      const context = this.buildTicketContext();
      return {
        id, sender: 'bot', timestamp: now, feedback: null,
        text: 'J\'ai rédigé un brouillon de ticket basé sur notre conversation. La description a été pré-remplie avec le contexte des derniers échanges :',
        jiraTicket: {
          summary:     'Incident détecté : ' + userText.substring(0, 55) + (userText.length > 55 ? '...' : ''),
          description: context,
          type: 'Bug', priority: 'Haute', project: 'COPILOT', assignee: 'Équipe Dev', status: 'draft'
        }
      };
    }

    if (lower.includes('restart') || lower.includes('redémarr') || lower.includes('systemctl') ||
        lower.includes('nginx') || lower.includes('exécut') || lower.includes('commande')) {
      const svc = lower.includes('nginx') ? 'nginx' : lower.includes('apache') ? 'apache2' : 'api-gateway';
      return {
        id, sender: 'bot', timestamp: now, feedback: null,
        text: 'Voici la séquence de commandes sécurisée. Chaque étape nécessite une confirmation avant exécution sur le serveur de production.',
        terminalCmds: [
          { cmd: `systemctl is-active ${svc}`, target: 'prod-server-01', status: 'idle', output: '' },
          { cmd: `systemctl reload ${svc}`, target: 'prod-server-01', status: 'idle', output: '' },
          { cmd: `systemctl status ${svc} --no-pager`, target: 'prod-server-01', status: 'idle', output: '' }
        ]
      };
    }

    if (lower.includes('script') || lower.includes('python') || lower.includes('bash') ||
        lower.includes('code') || lower.includes('typescript') || lower.includes('écrire') || lower.includes('génère')) {
      const lang: Artifact['type'] = lower.includes('bash') || lower.includes('sh') ? 'bash'
        : lower.includes('typescript') || lower.includes('ts') ? 'typescript' : 'python';
      return {
        id, sender: 'bot', timestamp: now, feedback: null,
        text: 'Script généré et ouvert dans le Canvas à droite. Vous pouvez le modifier, le copier, et utiliser "Apprendre de cette correction" pour améliorer l\'IA.',
        artifact: {
          id: `art-${id}`,
          type: lang,
          title: lang === 'bash' ? 'solution.sh' : lang === 'typescript' ? 'solution.ts' : 'solution.py',
          content: lang === 'bash'
            ? `#!/bin/bash\n# Script généré par DXC Copilot\nset -euo pipefail\n\nSERVICE="api-gateway"\nLOG_FILE="/var/log/dxc/ops_$(date +%Y%m%d_%H%M%S).log"\n\nlog() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }\n\nlog "Démarrage du script sur $(hostname)"\n\nif systemctl is-active --quiet "$SERVICE"; then\n  log "Service $SERVICE actif. Rechargement en douceur..."\n  systemctl reload "$SERVICE" && log "Rechargement OK" || {\n    log "Reload échoué — redémarrage forcé..."\n    systemctl restart "$SERVICE"\n  }\nelse\n  log "Service inactif. Démarrage..."\n  systemctl start "$SERVICE"\nfi\n\nlog "Statut final: $(systemctl is-active $SERVICE)"\nlog "Script terminé avec succès."`
            : lang === 'typescript'
            ? `// Script généré par DXC Copilot\nimport { execSync } from 'child_process';\nimport * as fs from 'fs';\n\nconst SERVICE = process.env['SERVICE'] ?? 'api-gateway';\nconst LOG_PATH = \`/var/log/dxc/ts_\${Date.now()}.log\`;\n\nfunction log(msg: string): void {\n  const line = \`[\${new Date().toISOString()}] \${msg}\`;\n  console.log(line);\n  fs.appendFileSync(LOG_PATH, line + '\\n');\n}\n\nfunction run(cmd: string): string {\n  try {\n    return execSync(cmd, { encoding: 'utf8' }).trim();\n  } catch (e: any) {\n    throw new Error(\`Command failed: \${cmd}\\n\${e.message}\`);\n  }\n}\n\nfunction main(): void {\n  log(\`Checking service: \${SERVICE}\`);\n  const status = run(\`systemctl is-active \${SERVICE}\`);\n  log(\`Status: \${status}\`);\n  if (status !== 'active') {\n    log('Service not active, starting...');\n    run(\`systemctl start \${SERVICE}\`);\n    log('Service started successfully.');\n  } else {\n    log('Service is healthy.');\n  }\n}\n\nmain();`
            : `# Script généré par DXC Copilot\nimport sys\nimport logging\nimport psutil\nfrom datetime import datetime\nfrom pathlib import Path\n\nlogging.basicConfig(\n    level=logging.INFO,\n    format='%(asctime)s [%(levelname)s] %(message)s',\n    handlers=[\n        logging.StreamHandler(),\n        logging.FileHandler(f'/var/log/dxc/copilot_{datetime.now():%Y%m%d}.log')\n    ]\n)\nlogger = logging.getLogger(__name__)\n\ndef collect_metrics() -> dict:\n    """Collecte les métriques système courantes."""\n    return {\n        'cpu_pct': psutil.cpu_percent(interval=1),\n        'mem_pct': psutil.virtual_memory().percent,\n        'disk_pct': psutil.disk_usage('/').percent,\n        'net_io': psutil.net_io_counters()._asdict(),\n        'timestamp': datetime.now().isoformat()\n    }\n\ndef main() -> int:\n    logger.info("Démarrage de la collecte de métriques...")\n    try:\n        metrics = collect_metrics()\n        for k, v in metrics.items():\n            logger.info(f"  {k}: {v}")\n        if metrics['mem_pct'] > 85:\n            logger.warning("ALERTE: Utilisation mémoire critique!")\n        logger.info("Collecte terminée avec succès.")\n        return 0\n    except Exception as e:\n        logger.error(f"Erreur: {e}")\n        return 1\n\nif __name__ == '__main__':\n    sys.exit(main())`,
          editMode: false,
          editedContent: '',
          corrected: false
        }
      };
    }

    return {
      id, sender: 'bot', timestamp: now, feedback: null,
      text: 'Je comprends votre demande. Je peux vous aider sur :\n• 📊 Analyse de logs et diagnostics d\'incidents\n• 🐍 Génération de scripts (Python, Bash, TypeScript) — ouverts dans le Canvas\n• ⚡ Exécution sécurisée de commandes sur vos serveurs\n• 🎫 Création de tickets Jira/ServiceNow depuis le chat\n• 📄 Génération de guides d\'incidents (après 3 occurrences similaires)\n\nPréférez-vous que je génère un script ou que je vous aide à diagnostiquer un problème ?'
    };
  }

  private buildTicketContext(): string {
    const lastMessages = this.messages
      .filter(m => m.sender === 'user' || m.sender === 'bot')
      .slice(-3);
    const contextLines = lastMessages.map(m => {
      const role   = m.sender === 'user' ? 'Utilisateur' : 'Copilot';
      const text   = m.text.substring(0, 200) + (m.text.length > 200 ? '...' : '');
      return `[${role}] ${text}`;
    }).join('\n\n');
    return `=== Contexte des derniers échanges ===\n\n${contextLines}\n\n=== Détails techniques ===\nSteps to reproduce : Voir logs API Gateway.\nImpact : Dégradation des performances.\nEnvironnement : Production / prod-server-01.`;
  }

  onKeyPress(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }

  // ── File Attachment ──────────────────────────────────────────
  attachFile(): void {
    this.fileInputRef.nativeElement.value = '';
    this.fileInputRef.nativeElement.click();
  }

  toggleMicrophone(): void {
    if (this.isRecording) {
      this.stopRecording();
    } else {
      this.startRecording();
    }
  }

  private startRecording(): void {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      this.showError('La reconnaissance vocale n\'est pas supportée par ce navigateur. Utilisez Chrome ou Edge.');
      return;
    }
    this.recognition = new SpeechRecognition();
    this.recognition.lang = 'fr-FR';
    this.recognition.continuous = true;
    this.recognition.interimResults = true;

    let finalTranscript = this.newMessage.trim() ? this.newMessage.trim() + ' ' : '';

    this.recognition.onresult = (event: any) => {
      let interimTranscript = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += t + ' ';
        } else {
          interimTranscript += t;
        }
      }
      this.newMessage = finalTranscript + interimTranscript;
      this.cdr.markForCheck();
    };

    this.recognition.onerror = (event: any) => {
      this.isRecording = false;
      this.recognition = null;
      if (event.error !== 'aborted') {
        this.showError('Erreur microphone : ' + event.error);
      }
      this.cdr.markForCheck();
    };

    this.recognition.onend = () => {
      // Auto-restart while still recording (browser stops after silence)
      if (this.isRecording) {
        try { this.recognition?.start(); } catch {}
      }
    };

    this.recognition.start();
    this.isRecording = true;
  }

  private stopRecording(): void {
    this.isRecording = false;
    if (this.recognition) {
      this.recognition.stop();
      this.recognition = null;
    }
    // Trim trailing space
    this.newMessage = this.newMessage.trim();
  }

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files) return;
    Array.from(input.files).forEach(f => this.processFile(f));
  }

  private processFile(file: File): void {
    const ext = '.' + file.name.split('.').pop()!.toLowerCase();
    if (!this.ALLOWED_MIME.has(file.type) && !this.ALLOWED_EXT.has(ext)) {
      this.showError('ERR1 — Format de fichier non supporté. Veuillez utiliser PNG, JPEG, PDF, TXT, MP3 ou WAV.');
      return;
    }
    const totalMb = (this.attachments.reduce((s, a) => s + a.size, 0) + file.size) / (1024 * 1024);
    if (totalMb > this.MAX_TOTAL_MB) {
      this.showError('ERR2 — Le volume total des pièces jointes dépasse la limite autorisée de 15 Mo.');
      return;
    }
    const kind: AttachedFile['kind'] =
      file.type.startsWith('image/') ? 'image' :
      file.type.startsWith('audio/') ? 'audio' : 'document';
    const attached: AttachedFile = { name: file.name, size: file.size, mimeType: file.type, kind };
    if (kind === 'image') {
      const reader = new FileReader();
      reader.onload = e => { attached.preview = e.target?.result as string; this.cdr.markForCheck(); };
      reader.readAsDataURL(file);
    }
    this.attachments.push(attached);
    this.pendingFile = file;
  }

  removeAttachment(i: number): void {
    this.attachments.splice(i, 1);
    if (this.attachments.length === 0) {
      this.pendingFile = null;
    }
  }

  formatSize(bytes: number): string {
    return bytes < 1024 * 1024 ? (bytes / 1024).toFixed(0) + ' Ko' : (bytes / 1024 / 1024).toFixed(1) + ' Mo';
  }

  get totalAttachmentsSize(): number {
    return this.attachments.reduce((sum, a) => sum + a.size, 0);
  }

  private showError(msg: string): void {
    this.errorNotification = msg;
    setTimeout(() => this.errorNotification = null, 5000);
  }

  async downloadGuide(guide: GuideCard): Promise<void> {
    // Real formatted PDF from the backend (reportlab)
    const g = guide as any;
    const incident = g.incident_type || g.incidentType || 'incident';
    try {
      const blob = await this.api.fetchPdf('/api/chat/guide-pdf', g);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `guide-rg2-${incident}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Fallback: plain-text download if the PDF endpoint is unreachable
      const content = `Guide de résolution — ${incident}\nOccurrences: ${g.occurrences}\nGénéré le: ${new Date().toLocaleDateString('fr-FR')}`;
      const blob = new Blob([content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `guide-${incident}.txt`; a.click();
      URL.revokeObjectURL(url);
    }
  }

  // ── Save reply as incident guide document ────────────────────
  saveAsDocument(msg: ChatMessage): void {
    if (msg.savedAsDocument) return;
    // Reconstruct full content: displayed text + artifact code if present
    const fullContent = msg.artifact
      ? msg.text + '\n\n```' + msg.artifact.type + '\n' + msg.artifact.content + '\n```'
      : msg.text;
    const firstLine = msg.text.split('\n').find(l => l.trim()) || msg.text;
    const title = 'Guide — ' + firstLine.replace(/[#*`]/g, '').trim().substring(0, 65);
    this.documentStore.addDocument({
      title,
      description: msg.text.replace(/```[\s\S]*?```/g, '[code]').substring(0, 500),
      category: 'Infrastructure',
      severity: 'P2',
      generatedFrom: 'Chat DXC Copilot — ' + new Date().toLocaleDateString('fr-FR'),
      tags: ['chat', 'copilot'],
      content: fullContent
    });
    msg.savedAsDocument = true;
    this.errorNotification = '✅ Réponse sauvegardée dans l\'onglet Documents — document 12 pages disponible.';
    setTimeout(() => { this.errorNotification = null; }, 4000);
  }

  useSuggestion(text: string): void {
    this.newMessage = text;
    this.sendMessage();
  }

  openSettings(): void {
    this.router.navigate(['/settings']);
  }

  ngOnDestroy(): void {
    this.stopRecording();
    // Clean up all active streaming intervals to prevent memory leaks
    this.activeIntervals.forEach(i => clearInterval(i));
    this.activeIntervals.clear();
    if (this.timeoutHandle) { clearTimeout(this.timeoutHandle); this.timeoutHandle = null; }
  }
}
