import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-admin-settings',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss'
})
export class AdminSettingsComponent implements OnInit {
  activeSection = 'general';
  savedFeedback = '';
  notifPreview: 'none' | 'teams' | 'slack' = 'none';

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.api.getAdminSettings().subscribe({
      next: (res: any) => {
        const s = res.settings || {};
        const sections = ['general','security','users','ai','notifications',
                          'integrations','storage','performance','appearance','audit'];
        for (const key of sections) {
          if (s[key] && typeof s[key] === 'object') {
            Object.assign((this as any)[key], s[key]);
          }
        }
      },
      error: () => {}
    });
  }

  sections = [
    { id: 'general',       icon: '🏢', label: 'Général' },
    { id: 'security',      icon: '🔒', label: 'Sécurité' },
    { id: 'users',         icon: '👥', label: 'Utilisateurs & Accès' },
    { id: 'ai',            icon: '🤖', label: 'IA & Modèles LLM' },
    { id: 'notifications', icon: '🔔', label: 'Notifications' },
    { id: 'integrations',  icon: '🔗', label: 'Intégrations' },
    { id: 'storage',       icon: '🗄️', label: 'Stockage & Données' },
    { id: 'performance',   icon: '⚡', label: 'Performance' },
    { id: 'appearance',    icon: '🎨', label: 'Apparence' },
    { id: 'audit',         icon: '📋', label: 'Audit & Conformité' },
    { id: 'knowledge',     icon: '🧠', label: 'Base de Connaissances' }
  ];

  // ── General ────────────────────────────────────────────────────
  general = {
    platformName: 'DXC Copilot',
    platformDescription: 'Plateforme d\'assistance intelligente propulsée par l\'IA pour les équipes DXC Technology.',
    adminEmail: 'admin@dxc.com',
    supportEmail: 'support@dxc.com',
    language: 'fr',
    timezone: 'Africa/Casablanca',
    dateFormat: 'DD/MM/YYYY',
    maintenanceMode: false,
    registrationOpen: false,
    maxConcurrentSessions: 3
  };

  // ── Security ───────────────────────────────────────────────────
  security = {
    minPasswordLength: 10,
    requireUppercase: true,
    requireNumbers: true,
    requireSpecialChars: true,
    passwordExpireDays: 90,
    maxFailedAttempts: 5,
    lockoutDurationMin: 15,
    sessionTimeoutMin: 30,
    extendSessionOnActivity: true,
    twoFactorRequired: false,
    twoFactorMethod: 'totp',
    ipWhitelistEnabled: false,
    ipWhitelist: '192.168.1.0/24\n10.0.0.0/8',
    jwtSecret: '••••••••••••••••••••••••••••••••',
    sslRequired: true,
    hstsDuration: 31536000,
    corsOrigins: 'https://copilot.dxc.com',
    rateLimitAuth: 10
  };

  // ── Users & Access ─────────────────────────────────────────────
  users = {
    maxUsers: 500,
    defaultRole: 'user',
    allowSelfRegistration: false,
    requireEmailVerification: true,
    allowProfileEdit: true,
    allowAvatarUpload: true,
    inactiveUserDays: 180,
    autoDeactivateInactive: true,
    ldapEnabled: false,
    ldapHost: 'ldap://ldap.dxc.com',
    ldapPort: 389,
    ldapBaseDn: 'dc=dxc,dc=com',
    ldapBindDn: 'cn=admin,dc=dxc,dc=com',
    ldapBindPassword: '',
    ssoEnabled: false,
    ssoProvider: 'saml',
    ssoEntryPoint: '',
    roles: [
      { name: 'Administrateur', users: 0, permissions: ['Tout accès'] },
      { name: 'Manager',        users: 0, permissions: ['Lecture', 'Rapports', 'Utilisateurs'] },
      { name: 'Utilisateur',    users: 0, permissions: ['Chat', 'Documents'] },
      { name: 'Invité',         users: 0, permissions: ['Chat lecture seule'] }
    ]
  };

  // ── AI & LLM ───────────────────────────────────────────────────
  ai = {
    defaultModel: 'gpt-4-turbo',
    fallbackModel: 'gpt-3.5-turbo',
    temperature: 0.7,
    maxTokens: 4096,
    contextWindow: 16000,
    topP: 0.9,
    frequencyPenalty: 0.1,
    presencePenalty: 0.1,
    systemPrompt: 'Tu es DXC Copilot, un assistant IA expert déployé au sein de DXC Technology. Tu aides les équipes avec du code, de la documentation et de l\'analyse technique. Tu répondras toujours en français sauf si l\'utilisateur parle une autre langue.',
    streamingEnabled: true,
    cacheResponses: true,
    cacheTtlMin: 60,
    rateLimitPerUser: 100,
    rateLimitPeriod: 'hour',
    maxRequestsPerMinute: 30,
    incidentThreshold: 3,
    autoGenerateGuide: true,
    contentFilterEnabled: true,
    contentFilterLevel: 'moderate',
    loggingEnabled: true,
    logPrompts: false
  };

  // ── Notifications ──────────────────────────────────────────────
  notifications = {
    emailEnabled: true,
    smtpHost: 'smtp.dxc.com',
    smtpPort: 587,
    smtpUser: 'noreply@dxc.com',
    smtpPassword: '',
    smtpTls: true,
    emailFromName: 'DXC Copilot',
    webhookEnabled: false,
    webhookUrl: '',
    webhookSecret: '',
    slackEnabled: false,
    slackWebhook: '',
    slackChannel: '#dxc-copilot-alerts',
    teamsEnabled: false,
    teamsWebhook: '',
    alertOnIncident: true,
    alertOnP1: true,
    alertOnP2: true,
    alertOnP3: false,
    alertOnHighLoad: true,
    loadThresholdPct: 85,
    alertOnNewUser: false,
    alertOnFailedLogin: true,
    digestFrequency: 'daily'
  };

  // ── Integrations ───────────────────────────────────────────────
  integrations = {
    jiraEnabled: false,
    jiraUrl: 'https://dxc.atlassian.net',
    jiraToken: '',
    jiraProject: 'COP',
    serviceNowEnabled: false,
    serviceNowInstance: 'dxc.service-now.com',
    serviceNowUser: '',
    serviceNowPassword: '',
    confluenceEnabled: false,
    confluenceUrl: 'https://dxc.atlassian.net/wiki',
    confluenceToken: '',
    confluenceSpace: 'COPILOT',
    githubEnabled: false,
    githubToken: '',
    githubOrg: 'DXCTechnology',
    apiKeyPublic: 'pk_live_••••••••••••••••••••••••',
    apiKeySecret: 'sk_live_••••••••••••••••••••••••',
    apiRateLimit: 1000,
    apiVersion: 'v2'
  };

  // ── Storage & Data ─────────────────────────────────────────────
  storage = {
    storageProvider: 's3',
    s3Bucket: 'dxc-copilot-prod',
    s3Region: 'eu-west-1',
    s3AccessKey: '',
    s3SecretKey: '',
    maxFileSizeMb: 50,
    allowedExtensions: 'pdf,docx,xlsx,pptx,txt,md,png,jpg',
    chatRetentionDays: 365,
    documentRetentionDays: 730,
    logRetentionDays: 90,
    backupEnabled: true,
    backupFrequency: 'daily',
    backupTime: '02:00',
    backupRetentionDays: 30,
    backupEncrypted: true,
    autoDeleteOldData: false,
    gdprDataExportEnabled: true,
    gdprDataDeletionEnabled: true
  };

  // ── Performance ────────────────────────────────────────────────
  performance = {
    cachingEnabled: true,
    redisCacheEnabled: true,
    redisTtlSeconds: 3600,
    redisMaxMemoryMb: 512,
    autoscalingEnabled: true,
    minInstances: 2,
    maxInstances: 20,
    scaleUpThresholdPct: 70,
    scaleDownThresholdPct: 30,
    healthCheckIntervalSec: 30,
    healthCheckTimeoutSec: 5,
    healthCheckRetries: 3,
    dbConnectionPoolMin: 5,
    dbConnectionPoolMax: 50,
    queryTimeoutSec: 30,
    slowQueryThresholdMs: 1000,
    compressionEnabled: true,
    cdnEnabled: false,
    cdnUrl: ''
  };

  // ── Appearance ─────────────────────────────────────────────────
  appearance = {
    theme: 'light',
    primaryColor: '#6D28D9',
    secondaryColor: '#4F46E5',
    accentColor: '#10B981',
    fontFamily: 'Inter',
    borderRadius: 'medium',
    sidebarStyle: 'dark',
    logoUrl: '',
    faviconUrl: '',
    loginBg: 'gradient',
    showPoweredBy: true,
    customCss: '',
    compactMode: false,
    animationsEnabled: true
  };

  // ── Audit & Compliance ─────────────────────────────────────────
  audit = {
    auditLogEnabled: true,
    auditLogRetentionDays: 365,
    logUserActions: true,
    logAdminActions: true,
    logApiCalls: true,
    logFailedLogins: true,
    logDataExports: true,
    rgpdCompliant: true,
    dataProcessingAgreement: true,
    cookieConsentEnabled: true,
    privacyPolicyUrl: 'https://dxc.com/privacy',
    termsUrl: 'https://dxc.com/terms',
    iso27001: true,
    soc2: true,
    exportFormat: 'json',
    reportFrequency: 'monthly',
    notifyDpo: true,
    dpoEmail: 'dpo@dxc.com'
  };

  // ── Knowledge Base ─────────────────────────────────────────────
  knowledgeStats = { total_docs: 0, total_chunks: 0, total_vectors: 0, last_updated: '—', backend: '' };
  knowledgeDocs: { id: string; filename: string; chunks: number; topic: string; uploaded_at: string }[] = [];
  knowledgeUploading = false;
  knowledgeDragOver = false;
  knowledgeSeedLoading = false;
  knowledgeStatsLoading = false;

  // Upload progress
  readonly KB_STAGES = ['Envoi', 'Extraction', 'Vectorisation', 'Index BM25'];
  knowledgeStageIdx = -1;   // -1 = idle
  knowledgeUploadPct = 0;
  knowledgeUploadError = '';
  knowledgeUploadSuccess = '';
  private kbStageTimer: any = null;

  loadKnowledgeStats(): void {
    this.knowledgeStatsLoading = true;
    this.api.getKnowledgeStats().subscribe({
      next: (res: any) => {
        this.knowledgeStats = { ...res, last_updated: res.last_updated || '—' };
        this.knowledgeStatsLoading = false;
      },
      error: (err: any) => {
        this.knowledgeStatsLoading = false;
        this.knowledgeUploadError = 'Impossible de charger les stats : ' + (err?.error?.detail || err?.message || 'Erreur serveur');
      }
    });
  }

  loadKnowledgeDocs(): void {
    this.api.getKnowledgeDocs().subscribe({
      next: (res: any) => { this.knowledgeDocs = res.documents || []; },
      error: () => {}
    });
  }

  onKnowledgeFileSelect(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files?.length) {
      this.uploadKnowledgeFile(input.files[0]);
      input.value = '';  // reset so same file can be re-selected
    }
  }

  onKnowledgeDrop(event: DragEvent): void {
    event.preventDefault();
    this.knowledgeDragOver = false;
    const file = event.dataTransfer?.files?.[0];
    if (file) this.uploadKnowledgeFile(file);
  }

  uploadKnowledgeFile(file: File): void {
    this.knowledgeUploading = true;
    this.knowledgeUploadError = '';
    this.knowledgeUploadSuccess = '';
    this.knowledgeStageIdx = 0;
    this.knowledgeUploadPct = 5;

    // Advance stages while server processes (OCR + embedding take time)
    let stageStep = 0;
    this.kbStageTimer = setInterval(() => {
      stageStep++;
      if (stageStep === 1) { this.knowledgeStageIdx = 1; this.knowledgeUploadPct = 30; }
      else if (stageStep === 2) { this.knowledgeStageIdx = 2; this.knowledgeUploadPct = 65; }
      else if (stageStep >= 3) { this.knowledgeUploadPct = Math.min(90, this.knowledgeUploadPct + 5); }
    }, 1800);

    this.api.uploadKnowledgeDoc(file).subscribe({
      next: (res: any) => {
        clearInterval(this.kbStageTimer);
        this.knowledgeStageIdx = 3;
        this.knowledgeUploadPct = 100;
        setTimeout(() => {
          this.knowledgeUploading = false;
          this.knowledgeStageIdx = -1;
          this.knowledgeUploadSuccess = `✅ "${res.filename}" ingéré avec succès — ${res.chunks_ingested} chunk(s) vectorisés.`;
          this.loadKnowledgeDocs();
          this.loadKnowledgeStats();
          setTimeout(() => this.knowledgeUploadSuccess = '', 8000);
        }, 500);
      },
      error: (err: any) => {
        clearInterval(this.kbStageTimer);
        this.knowledgeUploading = false;
        this.knowledgeStageIdx = -1;
        this.knowledgeUploadPct = 0;
        const detail = err?.error?.detail || err?.message || 'Échec de l\'ingestion';
        this.knowledgeUploadError = detail;
      }
    });
  }

  deleteKnowledgeDoc(docId: string, filename: string): void {
    if (!confirm(`Supprimer "${filename}" de la base de connaissances ?`)) return;
    this.api.deleteKnowledgeDoc(docId).subscribe({
      next: () => {
        this.knowledgeDocs = this.knowledgeDocs.filter(d => d.id !== docId);
        this.loadKnowledgeStats();
        this.savedFeedback = `"${filename}" supprimé.`;
        setTimeout(() => this.savedFeedback = '', 3000);
      },
      error: (err: any) => {
        this.savedFeedback = 'Erreur: ' + err.message;
        setTimeout(() => this.savedFeedback = '', 3000);
      }
    });
  }

  reseedKnowledge(): void {
    if (!confirm('Réinitialiser et recharger toutes les entrées intégrées de la base de connaissances ?')) return;
    this.knowledgeSeedLoading = true;
    this.api.seedKnowledge().subscribe({
      next: (res: any) => {
        this.knowledgeSeedLoading = false;
        this.savedFeedback = `Base réinitialisée — ${res.entries_seeded} entrées chargées.`;
        setTimeout(() => this.savedFeedback = '', 4000);
        this.loadKnowledgeDocs();
        this.loadKnowledgeStats();
      },
      error: (err: any) => {
        this.knowledgeSeedLoading = false;
        this.savedFeedback = 'Erreur: ' + err.message;
        setTimeout(() => this.savedFeedback = '', 4000);
      }
    });
  }

  setSection(id: string): void {
    this.activeSection = id;
    if (id === 'knowledge') {
      this.knowledgeUploadError = '';
      this.knowledgeUploadSuccess = '';
      this.loadKnowledgeStats();
      this.loadKnowledgeDocs();
    }
  }

  save(section: string): void {
    // Strip jwtSecret — it is a placeholder and must never overwrite the real secret
    const raw = (this as any)[section];
    const data = section === 'security'
      ? (({ jwtSecret, ...rest }) => rest)(raw)
      : raw;
    this.api.saveAdminSettings(section, data).subscribe({
      next: () => {
        this.savedFeedback = `Section "${this.sections.find(s => s.id === section)?.label}" sauvegardée avec succès.`;
        setTimeout(() => this.savedFeedback = '', 3000);
      },
      error: (err) => {
        this.savedFeedback = 'Erreur: ' + err.message;
        setTimeout(() => this.savedFeedback = '', 3000);
      }
    });
  }

  resetSection(section: string): void {
    const label = this.sections.find(s => s.id === section)?.label || section;
    if (!confirm(`Réinitialiser la section "${label}" aux valeurs par défaut ?`)) return;
    this.api.resetAdminSettings(section).subscribe({
      next: () => {
        this.savedFeedback = `Section "${label}" réinitialisée aux valeurs par défaut.`;
        setTimeout(() => this.savedFeedback = '', 3000);
        this.ngOnInit();
      },
      error: (err) => {
        this.savedFeedback = 'Erreur: ' + err.message;
        setTimeout(() => this.savedFeedback = '', 3000);
      }
    });
  }

  testingSmtp    = false;
  testingWebhook = false;
  regenLoading: 'public' | 'secret' | null = null;

  regenerateApiKey(type: 'public' | 'secret'): void {
    this.regenLoading = type;
    this.api.regenerateApiKey(type).subscribe({
      next: (res: any) => {
        if (type === 'public') this.integrations.apiKeyPublic  = res.key;
        else                   this.integrations.apiKeySecret = res.key;
        this.savedFeedback = `Clé ${type === 'public' ? 'publique' : 'secrète'} régénérée et sauvegardée.`;
        setTimeout(() => this.savedFeedback = '', 4000);
        this.regenLoading = null;
      },
      error: (err: any) => {
        this.savedFeedback = 'Erreur lors de la régénération : ' + (err?.error?.detail || err.message);
        setTimeout(() => this.savedFeedback = '', 4000);
        this.regenLoading = null;
      }
    });
  }

  testSmtp(): void {
    this.testingSmtp = true;
    this.api.testSmtp().subscribe({
      next: (res: any) => {
        this.savedFeedback = res.message || 'Email de test envoyé avec succès.';
        setTimeout(() => this.savedFeedback = '', 5000);
        this.testingSmtp = false;
      },
      error: (err: any) => {
        this.savedFeedback = 'Échec SMTP : ' + (err?.error?.detail || err.message);
        setTimeout(() => this.savedFeedback = '', 5000);
        this.testingSmtp = false;
      }
    });
  }

  testWebhook(): void {
    this.testingWebhook = true;
    this.api.testWebhook().subscribe({
      next: (res: any) => {
        this.savedFeedback = res.message || 'Payload de test envoyé au webhook.';
        setTimeout(() => this.savedFeedback = '', 5000);
        this.testingWebhook = false;
      },
      error: (err: any) => {
        this.savedFeedback = 'Échec webhook : ' + (err?.error?.detail || err.message);
        setTimeout(() => this.savedFeedback = '', 5000);
        this.testingWebhook = false;
      }
    });
  }

  previewAlert(platform: 'teams' | 'slack'): void {
    this.notifPreview = this.notifPreview === platform ? 'none' : platform;
  }
}
