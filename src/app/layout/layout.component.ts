import { Component, HostListener, OnDestroy, OnInit } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Subscription } from 'rxjs';
import { ThemeService } from '../services/theme.service';
import { ChatStoreService } from '../services/chat-store.service';
import { ApiService, ConversationSearchHit } from '../services/api.service';
import { SessionExpiryService } from '../services/session-expiry.service';

interface CmdItem {
  icon: string;
  label: string;
  category: 'navigation' | 'chat' | 'macro' | 'settings';
  action: () => void;
  shortcut?: string;
}

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule, RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './layout.component.html',
  styleUrls: ['./layout.component.scss']
})
export class LayoutComponent implements OnInit, OnDestroy {
  isSidebarOpen = false;
  isCollapsed = false;
  activeChatId: number | null = 1;
  showSessionWarning = false;
  isAdmin = false;
  private expirySubscription: Subscription | null = null;

  history: any[] = [];
  renamingChatId: any = null;
  renamingChatName = '';

  // ── Semantic conversation search ────────────────────────────────
  searchQuery = '';
  searchResults: ConversationSearchHit[] = [];
  searching = false;
  private searchDebounce: ReturnType<typeof setTimeout> | null = null;

  // ── Command Palette ─────────────────────────────────────────────
  showCmdPalette = false;
  cmdQuery = '';
  selectedCmdIndex = 0;

  private allCmdItems: CmdItem[] = [
    { icon: '💬', label: 'Nouveau chat',              category: 'navigation', shortcut: 'Ctrl+N', action: () => this.newChat() },
    { icon: '📄', label: 'Documents & guides',         category: 'navigation', action: () => this.router.navigate(['/viewer']) },
    { icon: '⚙️', label: 'Mes paramètres',             category: 'navigation', action: () => this.router.navigate(['/settings']) },
    { icon: '🔧', label: 'Administration',             category: 'navigation', action: () => this.router.navigate(['/admin']) },
    { icon: '🗑️', label: '/clear — Effacer la conversation', category: 'macro', action: () => this.clearActiveChat() },
    { icon: '🎫', label: '/new-ticket — Créer un ticket Jira', category: 'macro', action: () => this.triggerNewTicket() },
    { icon: '📊', label: '/report — Générer un rapport',       category: 'macro', action: () => this.router.navigate(['/admin/reports']) },
    { icon: '📌', label: '/pin — Épingler ce chat',           category: 'macro', action: () => this.pinActiveChat() },
    { icon: '👤', label: 'Paramètres: Profil',                category: 'settings', action: () => this.router.navigate(['/settings']) },
    { icon: '🔒', label: 'Paramètres: Sécurité',              category: 'settings', action: () => { this.router.navigate(['/settings']); } },
    { icon: '🔑', label: 'Paramètres: Clé API',               category: 'settings', action: () => this.router.navigate(['/settings']) },
  ];

  get filteredCmdItems(): CmdItem[] {
    const q = this.cmdQuery.toLowerCase().trim();
    if (!q) return this.allCmdItems.slice(0, 8);
    return this.allCmdItems.filter(item =>
      item.label.toLowerCase().includes(q) || item.category.includes(q)
    ).slice(0, 10);
  }

  get isDark(): boolean { return this.themeService.isDark; }

  toggleTheme(): void { this.themeService.toggle(); }

  constructor(
    private router: Router,
    private themeService: ThemeService,
    private chatStore: ChatStoreService,
    private api: ApiService,
    private sessionExpiry: SessionExpiryService
  ) {}

  ngOnDestroy(): void {
    this.expirySubscription?.unsubscribe();
  }

  ngOnInit(): void {
    this.expirySubscription = this.sessionExpiry.showWarning$.subscribe(
      v => { this.showSessionWarning = v; }
    );
    this.api.getUser().subscribe({
      next: (user: any) => { this.isAdmin = user?.role === 'admin'; },
      error: () => { this.isAdmin = false; }
    });
    this.loadSessions();
    this.chatStore.sessionCreated$.subscribe(session => {
      if (!this.history.find((h: any) => h.id === session.id)) {
        this.history.unshift({
          id: session.id,
          topic: session.title || 'Nouveau chat',
          time: new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }),
          pinned: false,
          showOptions: false
        });
        this.activeChatId = session.id as any;
      }
    });
  }

  loadSessions(): void {
    this.api.getSessions().subscribe({
      next: (sessions) => {
        this.history = sessions.map((s: any, i: number) => ({
          id: s.id || i + 1,
          topic: s.title || s.topic || 'Chat ' + (i + 1),
          time: s.updated_at ? new Date(s.updated_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : '',
          pinned: false,
          showOptions: false
        }));
      },
      error: () => {
        this.history = [];
        // Sessions unavailable — user will see empty state in sidebar
      }
    });
  }

  // ── Semantic conversation search ────────────────────────────────
  onSearchChange(): void {
    if (this.searchDebounce) clearTimeout(this.searchDebounce);
    const q = this.searchQuery.trim();
    if (!q) {
      this.searchResults = [];
      this.searching = false;
      return;
    }
    this.searching = true;
    this.searchDebounce = setTimeout(() => {
      this.api.searchConversations(q).subscribe({
        next: (res) => {
          this.searchResults = res.results || [];
          this.searching = false;
        },
        error: () => {
          this.searchResults = [];
          this.searching = false;
        }
      });
    }, 350);
  }

  openSearchResult(hit: ConversationSearchHit): void {
    this.activeChatId = hit.session_id as any;
    this.chatStore.selectBackendSession(hit.session_id);
    this.router.navigate(['/chat']);
    this.clearSearch();
  }

  clearSearch(): void {
    this.searchQuery = '';
    this.searchResults = [];
    this.searching = false;
    if (this.searchDebounce) { clearTimeout(this.searchDebounce); this.searchDebounce = null; }
  }

  dismissSessionWarning(): void {
    this.sessionExpiry.dismissWarning();
  }

  logout(): void {
    this.api.logout().subscribe({
      next: () => this.router.navigate(['/login']),
      error: () => this.router.navigate(['/login'])
    });
  }

  @HostListener('document:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
      event.preventDefault();
      this.toggleCmdPalette();
      return;
    }
    if (!this.showCmdPalette) return;
    if (event.key === 'Escape') { this.closeCmdPalette(); return; }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.selectedCmdIndex = Math.min(this.selectedCmdIndex + 1, this.filteredCmdItems.length - 1);
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.selectedCmdIndex = Math.max(this.selectedCmdIndex - 1, 0);
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const item = this.filteredCmdItems[this.selectedCmdIndex];
      if (item) this.runCmdItem(item);
    }
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (this.history.some(chat => chat.showOptions)) {
      this.history.forEach(chat => { chat.showOptions = false; });
    }
  }

  toggleCmdPalette(): void {
    this.showCmdPalette = !this.showCmdPalette;
    if (this.showCmdPalette) {
      this.cmdQuery = '';
      this.selectedCmdIndex = 0;
    }
  }

  closeCmdPalette(): void {
    this.showCmdPalette = false;
    this.cmdQuery = '';
  }

  runCmdItem(item: CmdItem): void {
    this.closeCmdPalette();
    item.action();
  }

  onCmdQueryChange(): void {
    this.selectedCmdIndex = 0;
  }

  categoryLabel(cat: string): string {
    const map: Record<string, string> = {
      navigation: 'Navigation', chat: 'Conversations', macro: 'Macros', settings: 'Paramètres'
    };
    return map[cat] || cat;
  }

  toggleSidebar(): void {
    this.isSidebarOpen = !this.isSidebarOpen;
  }

  closeSidebar(): void {
    this.isSidebarOpen = false;
  }

  toggleCollapse(): void {
    this.isCollapsed = !this.isCollapsed;
  }

  newChat(): void {
    this.activeChatId = null;
    this.chatStore.selectChat(0);
    this.router.navigate(['/chat']);
  }

  navigateToChat(chat: any): void {
    this.activeChatId = chat.id;
    if (typeof chat.id === 'string' && chat.id.includes('-')) {
      this.chatStore.selectBackendSession(chat.id);
    } else {
      this.chatStore.selectChat(Number(chat.id));
    }
    this.router.navigate(['/chat']);
  }

  toggleOptions(event: MouseEvent, chat: any): void {
    event.stopPropagation(); // Prevent document click listener from closing the menu immediately
    // Close other menus and toggle the current one
    this.history.forEach(c => c.showOptions = c.id === chat.id ? !c.showOptions : false);
  }

  pinChat(event: MouseEvent, chat: any): void {
    event.stopPropagation();
    chat.pinned = !chat.pinned;
    chat.showOptions = false;
  }

  startRenameChat(event: MouseEvent, chat: any): void {
    event.stopPropagation();
    chat.showOptions = false;
    this.renamingChatId = chat.id;
    this.renamingChatName = chat.topic;
  }

  saveRenameChat(chat: any): void {
    const name = this.renamingChatName.trim();
    if (!name) {
      this.renamingChatId = null;
      return; // Discard rename if name is empty
    }
    chat.topic = name;
    this.renamingChatId = null;
  }

  triggerNewTicket(): void {
    // Navigate to chat and emit an event to pre-fill ticket creation
    this.router.navigate(['/chat']).then(() => {
      // The chat component listens for this via chatStore
      this.chatStore.selectChat(0);
    });
  }

  cancelRenameChat(): void {
    this.renamingChatId = null;
  }

  shareChat(event: MouseEvent, chat: any): void {
    event.stopPropagation();
    chat.showOptions = false;
    const text = `[DXC Copilot] ${chat.topic} — partagé le ${new Date().toLocaleDateString('fr-FR')}`;
    navigator.clipboard.writeText(text).catch(() => {});
  }

  deleteChat(event: MouseEvent, chatToDelete: any): void {
    event.stopPropagation();
    chatToDelete.showOptions = false;
    if (confirm(`Supprimer le chat "${chatToDelete.topic}" ?`)) {
      this.history = this.history.filter(c => c.id !== chatToDelete.id);
      if (typeof chatToDelete.id === 'string' && chatToDelete.id.includes('-')) {
        this.api.deleteSession(chatToDelete.id).subscribe();
      }
    }
  }

  saveChatAs(event: MouseEvent, chat: any): void {
    event.stopPropagation();
    chat.showOptions = false;
    const data = JSON.stringify({ id: chat.id, topic: chat.topic, time: chat.time }, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${chat.topic.replace(/[^a-z0-9]/gi, '_')}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  clearActiveChat(): void {
    this.chatStore.selectChat(0);
    this.router.navigate(['/chat']);
  }

  pinActiveChat(): void {
    const active = this.history.find(c => c.id === this.activeChatId);
    if (active) {
      active.pinned = !active.pinned;
    }
  }
}
