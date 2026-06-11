import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../services/api.service';
import { DocumentStoreService } from '../services/document-store.service';

export interface DraftGuide {
  id: number;
  title: string;
  description: string;
  category: 'Performance' | 'Sécurité' | 'Infrastructure' | 'Disponibilité';
  severity: 'P1' | 'P2' | 'P3';
  generatedFrom: string;
  generatedAt: string;
  triggeredBy: string;
  occurrences: number;
  reviewNote: string;
  status: 'pending' | 'approved' | 'rejected' | 'changes_requested';
}

export interface IncidentDoc {
  id: number;
  title: string;
  description: string;
  category: 'Performance' | 'Sécurité' | 'Infrastructure' | 'Disponibilité';
  severity: 'P1' | 'P2' | 'P3';
  status: 'Résolu' | 'En cours' | 'Ouvert';
  date: string;
  size: string;
  pages: number;
  generatedFrom: string;
  tags: string[];
  content?: string; // raw chat text for user-created docs
}

export interface DocPage {
  type: 'cover' | 'toc' | 'content' | 'chart' | 'table' | 'conclusion';
  title: string;
  subtitle?: string;
  sections: DocSection[];
}

export interface DocSection {
  heading?: string;
  subheading?: string;
  text?: string;
  bullets?: string[];
  numbered?: string[];
  table?: { headers: string[]; rows: string[][] };
  metric?: { label: string; value: string; note?: string }[];
  highlight?: string;
}

@Component({
  selector: 'app-document-viewer',
  standalone: true,
  imports: [CommonModule, RouterLink, FormsModule],
  templateUrl: './document-viewer.component.html',
  styleUrl: './document-viewer.component.scss'
})
export class DocumentViewerComponent implements OnInit {
  constructor(private api: ApiService, private docStore: DocumentStoreService) {}

  loading = false;
  error = '';

  ngOnInit(): void {
    // Sync with store (live updates from chat)
    this.docStore.docs$.subscribe(docs => { this.allDocuments = docs; });
    this.loadGuides();
    this.loadDrafts();
  }

  loadGuides(): void {
    this.loading = true;
    this.api.getGuides().subscribe({
      next: (res: any) => {
        if (res.guides?.length) { this.docStore.setDocs(res.guides); }
        this.loading = false;
      },
      error: () => { this.loading = false; }
    });
  }

  loadDrafts(): void {
    this.api.getDraftGuides().subscribe({
      next: (res: any) => { this.pendingDrafts = res.drafts || []; },
      error: () => {}
    });
  }

  // ── Library state ──────────────────────────────────────────────
  selectedDoc: IncidentDoc | null = null;
  searchQuery = '';
  filterCategory = '';
  filterStatus = '';
  filterSeverity = '';

  // Populated by DocumentStoreService subscription (see ngOnInit)
  allDocuments: IncidentDoc[] = [];
  // ──────────────────────────────────────────────────────────────
  // Legacy placeholder kept for reference — data now comes from DocumentStoreService
  // ──────────────────────────────────────────────────────────────
  private _legacyPlaceholder: IncidentDoc[] = [
    {
      id: 1, title: 'Guide d\'incident — Saturation mémoire API Gateway',
      description: 'L\'API Gateway a atteint 98% d\'utilisation mémoire après un pic de trafic non anticipé. Ce guide documente le diagnostic, la résolution et les mesures préventives.',
      category: 'Infrastructure', severity: 'P2', status: 'Résolu',
      date: '08/10/2024', size: '1.8 MB', pages: 12, generatedFrom: 'Session : Analyse de perfor...',
      tags: ['memory', 'gateway', 'autoscaling']
    },
    {
      id: 2, title: 'Guide d\'incident — Timeout LLM Service',
      description: 'Le service LLM a produit des timeouts répétés lors de l\'inférence de modèles volumineux. Le guide couvre le rollback de version et la mise en place de circuit breakers.',
      category: 'Performance', severity: 'P2', status: 'Résolu',
      date: '15/11/2024', size: '2.1 MB', pages: 12, generatedFrom: 'Session : Revue de code',
      tags: ['llm', 'timeout', 'circuit-breaker']
    },
    {
      id: 3, title: 'Guide d\'incident — Pic de charge nocturne',
      description: 'Un pic inattendu de requêtes entre 02h et 04h a saturé les workers. Ce guide documente la mise en place du scaling automatique basé sur des métriques temporelles.',
      category: 'Infrastructure', severity: 'P2', status: 'Résolu',
      date: '03/12/2024', size: '1.5 MB', pages: 12, generatedFrom: 'Session : Optimisation SQL',
      tags: ['scaling', 'workers', 'cron']
    },
    {
      id: 4, title: 'Guide d\'incident — Dégradation Auth Service',
      description: 'Le service d\'authentification a répondu avec des latences anormales (>800ms) suite à une mauvaise configuration du cache Redis. Résolution par reconfiguration TTL.',
      category: 'Sécurité', severity: 'P3', status: 'Résolu',
      date: '22/11/2024', size: '1.2 MB', pages: 12, generatedFrom: 'Session : Documentation API',
      tags: ['auth', 'redis', 'latency']
    },
    {
      id: 5, title: 'Guide d\'incident — Erreurs 502 Bad Gateway',
      description: 'Des erreurs 502 intermittentes ont impacté 12% des requêtes pendant 45 minutes. Ce guide documente la correction du load balancer et les nouveaux health checks.',
      category: 'Disponibilité', severity: 'P2', status: 'En cours',
      date: '02/01/2025', size: '1.9 MB', pages: 12, generatedFrom: 'Session : Déploiement CI/CD',
      tags: ['502', 'load-balancer', 'health-check']
    },
    {
      id: 6, title: 'Guide d\'incident — Latence anormale Q1 2025',
      description: 'Une dégradation progressive de la latence de réponse a été détectée en janvier 2025. Analyse des causes liées à la fragmentation des index de base de données.',
      category: 'Performance', severity: 'P3', status: 'En cours',
      date: '14/01/2025', size: '2.3 MB', pages: 12, generatedFrom: 'Session : Analyse de perfor...',
      tags: ['latency', 'database', 'indexing']
    },
    {
      id: 7, title: 'Guide d\'incident — Fuite mémoire Queue Worker',
      description: 'Une fuite mémoire critique dans le service Queue Worker a provoqué des redémarrages en boucle. Guide de patch d\'urgence et refactoring du gestionnaire de messages.',
      category: 'Infrastructure', severity: 'P1', status: 'Résolu',
      date: '08/10/2024', size: '2.7 MB', pages: 12, generatedFrom: 'Session : Revue de code',
      tags: ['memory-leak', 'queue', 'worker']
    },
    {
      id: 8, title: 'Guide d\'incident — Interruption base de données',
      description: 'Une interruption de 18 minutes de la base de données principale due à une migration mal planifiée. Ce guide établit les procédures de migration sans downtime.',
      category: 'Disponibilité', severity: 'P1', status: 'Résolu',
      date: '25/09/2024', size: '3.1 MB', pages: 12, generatedFrom: 'Session : Optimisation SQL',
      tags: ['database', 'migration', 'downtime']
    },
    {
      id: 9, title: 'Guide d\'incident — Tentatives d\'accès suspectes',
      description: '1 842 tentatives d\'accès non autorisées détectées en provenance de 3 IP distinctes. Guide de durcissement du pare-feu et mise en place du rate limiting.',
      category: 'Sécurité', severity: 'P2', status: 'Résolu',
      date: '18/11/2024', size: '1.6 MB', pages: 12, generatedFrom: 'Session : Documentation API',
      tags: ['security', 'firewall', 'rate-limiting']
    },
    {
      id: 10, title: 'Guide d\'incident — Dépassement quota API externe',
      description: 'Le quota journalier de l\'API externe du fournisseur LLM a été dépassé suite à une boucle de retry non bornée. Guide d\'implémentation de backoff exponentiel.',
      category: 'Performance', severity: 'P3', status: 'Résolu',
      date: '30/10/2024', size: '1.4 MB', pages: 12, generatedFrom: 'Session : Optimisation SQL',
      tags: ['api-quota', 'retry', 'backoff']
    },
    {
      id: 11, title: 'Guide d\'incident — Crash Notification Service',
      description: 'Le microservice de notifications a crashé après une mise à jour de dépendances incompatible. Guide de rollback et stratégie de test des dépendances avant déploiement.',
      category: 'Infrastructure', severity: 'P3', status: 'Résolu',
      date: '22/11/2024', size: '1.3 MB', pages: 12, generatedFrom: 'Session : Déploiement CI/CD',
      tags: ['notification', 'dependency', 'rollback']
    },
    {
      id: 12, title: 'Guide d\'incident — Corruption cache Redis',
      description: 'Des données corrompues dans le cache Redis ont causé des réponses incohérentes pour 8% des utilisateurs. Guide de purge sélective et stratégie de validation du cache.',
      category: 'Infrastructure', severity: 'P2', status: 'Ouvert',
      date: '05/01/2025', size: '1.7 MB', pages: 12, generatedFrom: 'Session : Revue de code',
      tags: ['redis', 'cache', 'corruption']
    }
  ]; // end _legacyPlaceholder

  get filteredDocuments(): IncidentDoc[] {
    return this.allDocuments.filter(d => {
      const q = this.searchQuery.toLowerCase();
      const matchSearch = !q || d.title.toLowerCase().includes(q) ||
        d.description.toLowerCase().includes(q) || d.tags.some(t => t.includes(q));
      const matchCat = !this.filterCategory || d.category === this.filterCategory;
      const matchStatus = !this.filterStatus || d.status === this.filterStatus;
      const matchSev = !this.filterSeverity || d.severity === this.filterSeverity;
      return matchSearch && matchCat && matchStatus && matchSev;
    });
  }

  get totalResolved(): number { return this.allDocuments.filter(d => d.status === 'Résolu').length; }
  get totalInProgress(): number { return this.allDocuments.filter(d => d.status === 'En cours').length; }
  get totalOpen(): number { return this.allDocuments.filter(d => d.status === 'Ouvert').length; }

  openDocument(doc: IncidentDoc): void {
    this.selectedDoc = doc;
    this.currentDocPages = this.buildDocPages(doc);
    this.currentPage = 1;
    this.zoomLevel = 75;
  }

  closeDocument(): void { this.selectedDoc = null; }

  clearFilters(): void {
    this.searchQuery = '';
    this.filterCategory = '';
    this.filterStatus = '';
    this.filterSeverity = '';
  }

  // ── Create form state ──────────────────────────────────────────
  showCreateForm = false;
  newTagInput = '';
  newDocForm: Partial<IncidentDoc> = {
    title: '', description: '', category: 'Infrastructure',
    severity: 'P2', status: 'Ouvert', tags: []
  };

  openCreateForm(): void { this.showCreateForm = true; this.newDocForm = { title: '', description: '', category: 'Infrastructure', severity: 'P2', status: 'Ouvert', tags: [] }; this.newTagInput = ''; }
  closeCreateForm(): void { this.showCreateForm = false; }

  addTag(): void {
    const t = this.newTagInput.trim().toLowerCase().replace(/\s+/g, '-');
    if (t && !(this.newDocForm.tags ?? []).includes(t)) { (this.newDocForm.tags ??= []).push(t); }
    this.newTagInput = '';
  }
  removeTag(tag: string): void { this.newDocForm.tags = (this.newDocForm.tags ?? []).filter(t => t !== tag); }

  createDocument(): void {
    if (!this.newDocForm.title?.trim()) return;
    // Add to shared store immediately (works offline too)
    const doc = this.docStore.addDocument({
      title: this.newDocForm.title,
      description: this.newDocForm.description || 'Guide généré manuellement.',
      category: this.newDocForm.category,
      severity: this.newDocForm.severity,
      status: this.newDocForm.status,
      tags: this.newDocForm.tags ?? [],
      generatedFrom: 'Création manuelle'
    });
    this.showCreateForm = false;
    // Also try to persist via API
    this.api.createGuide({ ...doc, is_draft: false }).subscribe({ error: () => {} });
  }

  // ── Draft Review (Human-in-the-Loop) ───────────────────────────
  showReviewPanel = false;
  selectedDraft: DraftGuide | null = null;

  pendingDrafts: DraftGuide[] = [
    {
      id: 101,
      title: 'Guide d\'incident — Saturation CPU Service d\'Inférence',
      description: 'Le service d\'inférence LLM a atteint 98% d\'utilisation CPU lors du traitement simultané de 12 requêtes de grandes tailles. Ce guide documente l\'incident, les actions correctives et les règles de throttling à mettre en place.',
      category: 'Performance',
      severity: 'P2',
      generatedFrom: 'Session : Analyse de performance',
      generatedAt: '06/04/2025 09:42',
      triggeredBy: 'Jean Dupont (jean.dupont@dxc.com)',
      occurrences: 3,
      reviewNote: '',
      status: 'pending'
    },
    {
      id: 102,
      title: 'Guide d\'incident — Certificat SSL Expiré sur Environnement Staging',
      description: 'Le certificat SSL du sous-domaine staging.copilot.dxc.com a expiré sans renouvellement automatique, causant des erreurs HTTPS pour les équipes de test. Ce guide couvre le renouvellement et l\'automatisation via Let\'s Encrypt / cert-manager.',
      category: 'Sécurité',
      severity: 'P3',
      generatedFrom: 'Session : Déploiement CI/CD',
      generatedAt: '05/04/2025 16:18',
      triggeredBy: 'Marie Martin (marie.martin@dxc.com)',
      occurrences: 3,
      reviewNote: '',
      status: 'pending'
    },
    {
      id: 103,
      title: 'Guide d\'incident — Échec de Déploiement Canary (Rollback Automatique)',
      description: 'Le déploiement canary v2.4.1 a déclenché une hausse du taux d\'erreur à 8% dans les 5 premières minutes, entraînant un rollback automatique. Ce guide documente les critères de rollback et les tests pré-déploiement manquants.',
      category: 'Infrastructure',
      severity: 'P2',
      generatedFrom: 'Session : Revue de code',
      generatedAt: '04/04/2025 11:05',
      triggeredBy: 'Pierre Durand (pierre.durand@dxc.com)',
      occurrences: 4,
      reviewNote: '',
      status: 'pending'
    }
  ];

  get pendingDraftCount(): number {
    return this.pendingDrafts.filter(d => d.status === 'pending').length;
  }

  openReviewPanel(draft: DraftGuide): void {
    this.selectedDraft = draft;
    this.showReviewPanel = true;
  }

  closeReviewPanel(): void {
    this.showReviewPanel = false;
    this.selectedDraft = null;
  }

  approveDraft(draft: DraftGuide): void {
    this.api.approveGuide(draft.id).subscribe({
      next: () => {
        draft.status = 'approved';
        this.loadGuides();
        this.closeReviewPanel();
        alert(`✅ Guide "${draft.title.substring(0, 40)}..." approuvé et ajouté à la base de connaissances.`);
      },
      error: (e: any) => alert('Erreur : ' + e.message)
    });
  }

  requestChanges(draft: DraftGuide): void {
    if (!draft.reviewNote.trim()) {
      alert('Veuillez ajouter une note expliquant les modifications demandées.');
      return;
    }
    this.api.updateGuide(draft.id, { reviewNote: draft.reviewNote, is_draft: true }).subscribe({
      next: () => {
        draft.status = 'changes_requested';
        this.closeReviewPanel();
        alert(`📝 Modifications demandées envoyées à l'auteur : ${draft.triggeredBy}`);
      },
      error: (e: any) => alert('Erreur : ' + e.message)
    });
  }

  rejectDraft(draft: DraftGuide): void {
    if (confirm(`Rejeter définitivement le guide "${draft.title.substring(0, 50)}..." ?`)) {
      this.api.deleteGuide(draft.id).subscribe({
        next: () => {
          draft.status = 'rejected';
          this.pendingDrafts = this.pendingDrafts.filter(d => d.id !== draft.id);
          this.closeReviewPanel();
        },
        error: (e: any) => alert('Erreur : ' + e.message)
      });
    }
  }

  severityColor(sev: string): string {
    return sev === 'P1' ? '#DC2626' : sev === 'P2' ? '#D97706' : '#059669';
  }

  // ── Viewer state ───────────────────────────────────────────────
  currentPage = 1;
  get totalPages(): number { return this.currentDocPages.length; }
  zoomLevel = 75;
  currentDocPages: DocPage[] = [];

  private specs: Record<number, any> = {
    1: { period: '08/10/2024 — 08/10/2024', duration: '42 min', sev: 'P2', service: 'API Gateway', impact: '23% des requêtes échouées', uptime: '99.91%', latency: '980 ms', errors: '23%', rca: 'Absence de règles d\'autoscaling proactif. Le seuil d\'alerte mémoire était fixé à 95% sans trigger de scaling.', rcaBullets: ['Pic de trafic +340% non anticipé', 'Absence de scaling automatique sur métriques mémoire', 'Seuil d\'alerte trop tardif (95%)', 'Aucun circuit breaker sur les consumers'], steps: ['Redémarrage d\'urgence de l\'API Gateway', 'Augmentation manuelle des ressources mémoire (+4 GB)', 'Activation des règles d\'autoscaling sur seuil 70%', 'Déploiement du patch d\'optimisation mémoire v1.3.2', 'Validation des health checks et smoke tests'], prevention: ['Définir seuil d\'autoscaling à 70% (vs 95%)', 'Mettre en place un load testing hebdomadaire', 'Ajouter alertes PagerDuty sur métriques mémoire', 'Implémenter circuit breaker sur tous les consumers'], conclusion: 'L\'incident a été résolu en 42 minutes sans perte de données. Le déploiement des règles d\'autoscaling proactives prévient toute récurrence.' },
    2: { period: '15/11/2024 — 15/11/2024', duration: '18 min', sev: 'P2', service: 'LLM Service', impact: '100% des inférences >30s ont échoué', uptime: '99.95%', latency: '>30 000 ms', errors: '18%', rca: 'Déploiement du modèle v2.3 sans chunking des requêtes volumineuses. Les inputs >8K tokens saturaient le contexte du modèle.', rcaBullets: ['Absence de validation de taille d\'input avant inférence', 'Modèle v2.3 incompatible avec tokens >8K sans chunking', 'Absence de timeout au niveau applicatif', 'Circuit breaker non activé sur le service LLM'], steps: ['Rollback immédiat vers LLM Service v2.1', 'Activation du circuit breaker avec seuil 5s', 'Déploiement du middleware de chunking automatique', 'Tests de charge avec inputs variés (1K à 32K tokens)', 'Mise en production du LLM Service v2.3.1 corrigé'], prevention: ['Valider la taille d\'input avant chaque inférence', 'Tester tous les modèles avec inputs >8K tokens en staging', 'Définir un timeout applicatif de 10s sur le LLM Service', 'Automatiser le rollback si error rate >5%'], conclusion: 'Le rollback vers v2.1 a rétabli le service en 18 minutes. Le middleware de chunking déployé en v2.3.1 prévient la récurrence.' },
    3: { period: '03/12/2024 — 03/12/2024', duration: '31 min', sev: 'P2', service: 'Queue Worker', impact: 'File de traitement saturée à 100%', uptime: '99.91%', latency: '4 200 ms', errors: '31%', rca: 'Un batch job de réindexation planifié à 02h00 a déclenché un pic de charge coïncidant avec les accès nocturnes de l\'équipe Asie-Pacifique.', rcaBullets: ['Batch job planifié sans analyse des patterns de trafic', 'Absence de priorisation des tâches dans la file', 'Aucun throttling sur le batch de réindexation', 'Scaling nocturne réduit à 40% de capacité'], steps: ['Annulation du batch job en cours', 'Scale-up manuel des workers × 3', 'Reprogrammation du batch à 04h30 (creux de trafic)', 'Déploiement d\'un scheduler intelligent basé sur les métriques', 'Configuration du throttling batch à 20% de la capacité max'], prevention: ['Analyser les patterns de trafic avant planification des batchs', 'Implémenter un scheduler respectant les fenêtres de maintenance', 'Throttling obligatoire pour tous les batchs (max 20%)', 'Maintenir 80% de capacité min la nuit'], conclusion: 'La saturation a été résolue en 31 minutes. Le nouveau scheduler intelligent évite tout conflit entre batchs et trafic utilisateur.' },
    4: { period: '22/11/2024 — 22/11/2024', duration: '25 min', sev: 'P3', service: 'Auth Service', impact: '40% des utilisateurs avec latence >800ms', uptime: '99.97%', latency: '840 ms', errors: '2%', rca: 'La configuration du TTL Redis a été réinitialisée à 0 lors d\'une mise à jour de configuration, désactivant le cache de sessions.', rcaBullets: ['TTL Redis remis à 0 par script de migration automatique', 'Absence de validation post-déploiement du cache', 'Pas d\'alerting sur le taux de cache hit Redis', 'Tests de non-régression ne couvrant pas la config cache'], steps: ['Identification du TTL Redis à 0 via monitoring', 'Reconfiguration TTL à 3 600 secondes (1 heure)', 'Vidage et rechargement du cache de sessions', 'Validation du taux de cache hit (objectif >85%)', 'Déploiement de checks post-migration automatiques'], prevention: ['Ajouter validation TTL Redis dans les checks post-déploiement', 'Alerting sur cache hit rate <80%', 'Tests de non-régression couvrant toutes les configs cache', 'Revue obligatoire des scripts de migration'], conclusion: 'La reconfiguration du TTL Redis a rétabli les performances en 25 minutes. Les checks automatiques post-déploiement évitent toute récurrence.' },
    5: { period: '02/01/2025 — En cours', duration: '45 min (partiel)', sev: 'P2', service: 'Load Balancer', impact: '12% des requêtes retournaient 502', uptime: '99.83%', latency: '2 100 ms', errors: '12%', rca: 'La mise à jour du load balancer v3.2 a introduit un changement de comportement sur les health checks (header X-Health requis mais non envoyé).', rcaBullets: ['Breaking change dans le protocole de health check v3.2', 'Absence de tests de compatibilité LB en staging', 'Health checks des backends considérés comme DOWN à tort', 'Aucun canary deploy pour la mise à jour LB'], steps: ['Identification des backends incorrectement marqués DOWN', 'Rollback partiel du LB vers v3.1 sur 2 des 3 noeuds', 'Ajout du header X-Health aux backends', 'Tests de validation en cours sur le 3ème noeud', 'Mise à jour de la documentation de déploiement LB'], prevention: ['Canary deploy obligatoire pour toutes les mises à jour LB', 'Tests de compatibilité health check en staging', 'Monitoring du taux de backends DOWN post-déploiement', 'Changelog obligatoire pour les breaking changes'], conclusion: 'La résolution est en cours. 2/3 des noeuds ont été corrigés. La résolution complète est prévue sous 24h.' },
    6: { period: '14/01/2025 — En cours', duration: 'Continu (+3 jours)', sev: 'P3', service: 'PostgreSQL', impact: 'Latence +35% vs baseline', uptime: '100%', latency: '540 ms', errors: '0.1%', rca: 'Fragmentation progressive des index PostgreSQL après 6 mois sans REINDEX. Les index btree sur les tables de sessions (>50M lignes) ont atteint un taux de fragmentation de 67%.', rcaBullets: ['Absence de maintenance planifiée des index PostgreSQL', 'Croissance des tables non anticipée (×3 en 6 mois)', 'Pas d\'alerting sur la fragmentation des index', 'AUTOVACUUM insuffisant pour les tables haute fréquence'], steps: ['Diagnostic via pg_stat_user_indexes : fragmentation 67%', 'Planification d\'une fenêtre de maintenance REINDEX CONCURRENTLY', 'REINDEX CONCURRENTLY sur les 5 tables les plus fragmentées', 'Mise en place de VACUUM ANALYZE automatique hebdomadaire', 'Monitoring post-maintenance en cours'], prevention: ['Planifier REINDEX CONCURRENTLY mensuel sur les grandes tables', 'Alerting sur fragmentation index >30%', 'Dimensionner AUTOVACUUM selon la charge réelle', 'Surveiller la croissance des tables mensuellement'], conclusion: 'L\'opération de REINDEX est planifiée pour la prochaine fenêtre de maintenance (weekend). La dégradation est en cours de suivi actif.' },
    7: { period: '08/10/2024 — 08/10/2024', duration: '67 min', sev: 'P1', service: 'Queue Worker', impact: 'Service Queue Worker totalement indisponible', uptime: '99.84%', latency: 'N/A (service KO)', errors: '100%', rca: 'Un event listener attaché à chaque connexion WebSocket n\'était jamais supprimé à la déconnexion. Après 4h de fonctionnement, la mémoire Node.js atteignait 98%.', rcaBullets: ['Event listener non supprimé sur événement "disconnect"', 'Absence de monitoring de la consommation mémoire par processus', 'Aucun redémarrage automatique avec préservation de la file', 'Tests de charge ne simulant pas les connexions/déconnexions répétées'], steps: ['Redémarrage d\'urgence du service avec préservation de la file Redis', 'Déploiement du patch de suppression des event listeners', 'Validation : test de 10 000 connect/disconnect sans fuite', 'Activation du monitoring mémoire par processus (seuil 80%)', 'Refactoring complet du gestionnaire de connexions WebSocket'], prevention: ['Code review obligatoire pour tout event listener', 'Tests de stress simulant 10K connect/disconnect', 'Alerting mémoire par processus à 80%', 'Redémarrage automatique gracieux si mémoire >90%'], conclusion: 'Incident P1 résolu en 67 min. Le refactoring du gestionnaire WebSocket élimine définitivement la fuite mémoire.' },
    8: { period: '25/09/2024 — 25/09/2024', duration: '18 min', sev: 'P1', service: 'PostgreSQL Primary', impact: '100% des opérations read/write bloquées', uptime: '99.96%', latency: 'N/A (DB inaccessible)', errors: '100%', rca: 'La migration de schéma v14 a été exécutée directement en production sans blue-green deployment, bloquant les connexions pendant le verrou de table.', rcaBullets: ['Migration exécutée sans procédure blue-green', 'Verrou exclusif sur les tables principales pendant 18 min', 'Absence de fenêtre de maintenance approuvée', 'Rollback non testé avant la migration'], steps: ['Attente de fin de migration (impossible de rollback à chaud)', 'Vérification de l\'intégrité des données post-migration', 'Test de fonctionnement sur tous les services connectés', 'Documentation de la procédure de migration sans downtime', 'Formation de l\'équipe sur les migrations online (pg_repack)'], prevention: ['Toute migration doit utiliser pg_repack ou migration online', 'Fenêtre de maintenance obligatoire avec approbation CAB', 'Tests de rollback en staging avant chaque migration', 'Interdiction de migrations DDL directes en production'], conclusion: 'La migration s\'est terminée sans perte de données après 18 min. La nouvelle procédure de migration online est maintenant obligatoire.' },
    9: { period: '18/11/2024 — 18/11/2024', duration: '0 min (bloqué)', sev: 'P2', service: 'Auth Service / Firewall', impact: '1 842 tentatives bloquées, 0 intrusion réussie', uptime: '100%', latency: '12 ms', errors: '0%', rca: 'Absence de rate limiting sur l\'endpoint /auth/login. 3 adresses IP ont exécuté des attaques brute-force de 02h00 à 06h30.', rcaBullets: ['Aucun rate limiting sur /auth/login', 'Absence de détection d\'anomalies comportementales', 'Pas de blacklist automatique des IPs suspectes', 'Alerting déclenché trop tardivement (après 500 tentatives)'], steps: ['Blacklist immédiate des 3 IPs sources via firewall', 'Déploiement du rate limiting : 5 tentatives / IP / minute', 'Activation de CAPTCHA après 3 échecs consécutifs', 'Revue des logs pour vérifier l\'absence d\'intrusion réussie', 'Déploiement du système de détection d\'anomalies basé sur ML'], prevention: ['Rate limiting sur tous les endpoints d\'authentification', 'Blacklist automatique après 10 échecs en 5 minutes', 'Alerting dès la 1ère tentative suspecte détectée', 'Audit de sécurité trimestriel des endpoints publics'], conclusion: 'Aucune intrusion réussie. Les 1 842 tentatives ont toutes été bloquées. Le système de rate limiting est désormais actif.' },
    10: { period: '30/10/2024 — 30/10/2024', duration: '120 min (reset quota)', sev: 'P3', service: 'LLM API Externe', impact: '8% des requêtes LLM bloquées', uptime: '100%', latency: '45 000 ms (quota exceeded)', errors: '8%', rca: 'Un bug dans le gestionnaire de retry exécutait des boucles infinies sans condition de sortie sur erreur 429, épuisant le quota en 2 heures.', rcaBullets: ['Retry loop sans condition de sortie sur erreur 429', 'Absence de compteur de tentatives maximal', 'Quota journalier non monitoré', 'Aucun circuit breaker sur les appels API externes'], steps: ['Arrêt d\'urgence du gestionnaire de retry bogué', 'Attente du reset du quota (minuit UTC)', 'Déploiement du backoff exponentiel avec jitter', 'Implémentation du circuit breaker sur les appels externes', 'Mise en place du monitoring de quota en temps réel'], prevention: ['Backoff exponentiel obligatoire sur toutes les APIs externes', 'Max 3 tentatives avant abandon sur erreur 429', 'Alerting à 80% du quota journalier consommé', 'Circuit breaker sur tous les services tiers'], conclusion: 'Le quota a été rétabli à minuit. Le backoff exponentiel déployé prévient tout dépassement futur.' },
    11: { period: '22/11/2024 — 22/11/2024', duration: '25 min', sev: 'P3', service: 'Notification Service', impact: 'Notifications non envoyées pendant 25 min', uptime: '99.96%', latency: 'N/A (crash)', errors: '100%', rca: 'La mise à jour automatique de la dépendance nodemailer vers v4.2.0 a introduit un breaking change dans l\'API de configuration du transport SMTP.', rcaBullets: ['Dépendances avec version "latest" en package.json', 'Absence de tests d\'intégration couvrant le transport SMTP', 'Mise à jour automatique des dépendances en staging non testée', 'Aucun lock file committé (package-lock.json ignoré)'], steps: ['Identification du breaking change dans nodemailer v4.2.0', 'Rollback vers nodemailer v4.1.8', 'Correction de la configuration transport pour v4.2.0', 'Verrouillage de toutes les dépendances avec versions exactes', 'Ajout de tests d\'intégration SMTP dans la pipeline CI'], prevention: ['Interdire "latest" en package.json — utiliser des versions exactes', 'Committer package-lock.json dans tous les repos', 'Tests d\'intégration couvrant les services tiers (SMTP, etc.)', 'Revue manuelle de tout changelog avant mise à jour de dépendance'], conclusion: 'Le service a été rétabli en 25 min via rollback. La politique de gestion des dépendances a été entièrement révisée.' },
    12: { period: '05/01/2025 — En cours', duration: 'Continu (+2 jours)', sev: 'P2', service: 'Redis Cache', impact: '8% des utilisateurs reçoivent des données incorrectes', uptime: '100%', latency: '28 ms', errors: '0.5%', rca: 'Une désynchronisation entre les opérations d\'écriture et l\'invalidation du cache Redis a créé des entrées corrompues persistant jusqu\'à expiration du TTL (24h).', rcaBullets: ['Absence de stratégie cache-aside cohérente', 'Invalidation du cache non atomique avec l\'écriture DB', 'TTL trop long (24h) pour les données fréquemment modifiées', 'Aucun mécanisme de validation des données lues depuis le cache'], steps: ['Identification des clés corrompues via scan Redis', 'Purge sélective des 847 clés corrompues identifiées', 'Réduction temporaire du TTL à 1h pour les données sensibles', 'Implémentation du pattern Write-Through en cours', 'Validation des données post-purge par échantillonnage'], prevention: ['Implémenter le pattern Write-Through pour toutes les écritures critiques', 'Réduire le TTL des données mutables à 30 min max', 'Ajouter checksums sur les valeurs critiques cachées', 'Alerting sur taux d\'erreurs de validation cache >0.1%'], conclusion: 'La purge sélective est en cours. L\'implémentation du pattern Write-Through préviendra toute désynchronisation future.' }
  };

  get page(): DocPage {
    return this.currentDocPages[this.currentPage - 1];
  }

  /** Convert raw markdown text into 12 structured DocPages for user-created chat docs */
  private parseMarkdownToPages(content: string, doc: IncidentDoc): DocPage[] {
    // Strip code fences, normalize whitespace
    const stripped = content.replace(/```[\s\S]*?```/g, '[code omis — voir Canvas]').trim();

    // --- Smart section splitting: markdown headers → numbered items → paragraphs ---
    let rawBlocks: string[];
    if (/\n#{1,3} /.test(stripped)) {
      // Markdown headers (## Title or # Title)
      rawBlocks = stripped.split(/\n(?=#{1,3} )/);
    } else if (/\n\d+\.\s/.test(stripped)) {
      // Numbered list (1. text, 2. text …) — most common AI response format
      rawBlocks = stripped.split(/\n(?=\d+\.\s)/);
    } else {
      // Fall back to paragraph breaks
      rawBlocks = stripped.split(/\n{2,}/);
    }
    rawBlocks = rawBlocks.filter(b => b.trim());

    const sections: { heading: string; body: string }[] = rawBlocks.map(block => {
      const lines = block.split('\n');
      let firstLine = lines[0].replace(/^#+\s*/, '').trim() || 'Contenu';
      let rest = lines.slice(1).join('\n').trim();

      // "1. **Bold title** : body text" → heading = "Bold title"
      const boldInNumber = firstLine.match(/^\d+\.\s+\*\*([^*]+)\*\*\s*[:\-–]?\s*(.*)/);
      if (boldInNumber) {
        return {
          heading: boldInNumber[1].trim(),
          body: [boldInNumber[2].trim(), rest].filter(Boolean).join(' ')
        };
      }

      // "**Bold title** : body text" → heading = "Bold title"
      const boldOnly = firstLine.match(/^\*\*([^*]+)\*\*\s*[:\-–]?\s*(.*)/);
      if (boldOnly) {
        return {
          heading: boldOnly[1].trim(),
          body: [boldOnly[2].trim(), rest].filter(Boolean).join(' ')
        };
      }

      // "3. Plain title" → heading = "Plain title"
      const numbered = firstLine.match(/^\d+\.\s+(.+)/);
      if (numbered) {
        return { heading: numbered[1].trim(), body: rest || numbered[1].trim() };
      }

      return { heading: firstLine, body: rest || firstLine };
    });

    // Helper: convert a body string to bullets if it has "- " lines, else plain text
    const toSection = (heading: string, body: string): DocSection => {
      const bulletLines = body.split('\n').filter(l => l.match(/^[-*]\s+/));
      const textLines   = body.split('\n').filter(l => !l.match(/^[-*]\s+/)).join(' ').trim();
      if (bulletLines.length > 0) {
        return { heading, bullets: bulletLines.map(l => l.replace(/^[-*]\s+/, '')), text: textLines || undefined };
      }
      return { heading, text: body.replace(/\n+/g, ' ').trim() };
    };

    // Distribute sections across content pages 3-10 (8 content pages)
    const contentPages: DocPage[] = [];
    const sectionChunks: { heading: string; body: string }[][] = [];
    const chunkSize = Math.ceil(sections.length / 8);
    for (let i = 0; i < sections.length; i += chunkSize) {
      sectionChunks.push(sections.slice(i, i + chunkSize));
    }
    // Ensure 8 groups (pad with empty if needed)
    while (sectionChunks.length < 8) sectionChunks.push([]);

    const pageLabels = [
      'Résumé et contexte', 'Analyse technique', 'Détails de l\'implémentation',
      'Architecture et design', 'Considérations de sécurité', 'Tests et validation',
      'Optimisations et bonnes pratiques', 'Références et ressources'
    ];

    for (let pi = 0; pi < 8; pi++) {
      const chunk = sectionChunks[pi];
      const pageSections: DocSection[] = chunk.length > 0
        ? chunk.map(s => toSection(s.heading, s.body))
        : [{ text: 'Voir les sections adjacentes pour le contenu complet.' }];
      contentPages.push({
        type: 'content',
        title: `${pi + 3}. ${pageLabels[pi]}`,
        sections: pageSections
      });
    }

    const shortDesc = stripped.substring(0, 400).replace(/\n+/g, ' ');
    const keyPoints = sections.slice(0, 5).map(s => s.heading);

    return [
      // Page 1 — Cover
      { type: 'cover', title: doc.title,
        subtitle: `Guide généré depuis Chat — ${doc.category} · ${doc.severity} · ${doc.status}`,
        sections: [
          { metric: [
            { label: 'Date', value: doc.date },
            { label: 'Catégorie', value: doc.category },
            { label: 'Sévérité', value: doc.severity },
            { label: 'Statut', value: doc.status },
            { label: 'Source', value: doc.generatedFrom },
            { label: 'Tags', value: doc.tags.join(', ') || '—' }
          ]},
          { highlight: 'Ce document a été généré automatiquement par DXC Copilot IA depuis une session de chat. Usage interne DXC Technology uniquement.' }
        ]
      },
      // Page 2 — TOC
      { type: 'toc', title: 'Table des matières',
        sections: [{ numbered: [
          '1. Résumé et contexte ........................................................ 3',
          '2. Analyse technique .......................................................... 4',
          '3. Détails de l\'implémentation ................................................ 5',
          '4. Architecture et design ..................................................... 6',
          '5. Considérations de sécurité ................................................. 7',
          '6. Tests et validation ........................................................ 8',
          '7. Optimisations et bonnes pratiques .......................................... 9',
          '8. Références et ressources ................................................... 10',
          '9. Recommandations ............................................................. 11',
          '10. Conclusion ................................................................. 12'
        ]}]
      },
      // Pages 3-10 — Content
      ...contentPages,
      // Page 11 — Recommendations
      { type: 'content', title: '9. Recommandations',
        sections: [
          { heading: '9.1 Points clés identifiés', bullets: keyPoints.length > 0 ? keyPoints : ['Analyser les éléments décrits dans ce guide'] },
          { heading: '9.2 Prochaines étapes', numbered: [
            'Revue technique par un pair avant mise en production',
            'Documenter les changements dans le système de suivi de versions',
            'Planifier des tests de régression',
            'Mettre à jour la documentation existante',
            'Former l\'équipe sur les nouvelles pratiques'
          ]}
        ]
      },
      // Page 12 — Conclusion
      { type: 'conclusion', title: '10. Conclusion',
        sections: [
          { text: shortDesc },
          { heading: '10.1 Bilan', table: { headers: ['Critère', 'Résultat'], rows: [
            ['Documentation générée', '✔ Complète'],
            ['Revue requise', '⚠ Recommandée'],
            ['Confidentialité', '✔ Usage interne'],
            ['Source vérifiée', '✔ Chat DXC Copilot']
          ]}},
          { highlight: `Document généré automatiquement par DXC Copilot IA — ${doc.date} — Confidentiel` }
        ]
      }
    ];
  }

  buildDocPages(doc: IncidentDoc): DocPage[] {
    // User-created docs from chat have content and id > 1000
    if (doc.content && doc.id > 1000) {
      return this.parseMarkdownToPages(doc.content, doc);
    }
    const s = this.specs[doc.id] ?? this.specs[1];
    return [
      { type: 'cover', title: doc.title, subtitle: `Guide de résolution — ${doc.category} · ${s.sev} · ${doc.status}`,
        sections: [{ metric: [{ label: 'Date', value: doc.date }, { label: 'Service', value: s.service }, { label: 'Durée', value: s.duration }, { label: 'Sévérité', value: s.sev }, { label: 'Statut', value: doc.status }, { label: 'Généré depuis', value: doc.generatedFrom }] }, { highlight: 'Ce guide d\'incident est confidentiel — Usage interne DXC Technology uniquement.' }]
      },
      { type: 'toc', title: 'Table des matières',
        sections: [{ numbered: ['Résumé exécutif .............................................................. 3', 'Description de l\'incident .................................................. 4', 'Chronologie ..................................................................... 5', 'Analyse d\'impact ............................................................. 6', 'Cause racine (RCA) .......................................................... 7', 'Mesures de résolution ....................................................... 8', 'Tests et validation ............................................................ 9', 'Indicateurs post-incident ................................................... 10', 'Recommandations et prévention ........................................ 11', 'Conclusion et bilan ........................................................... 12'] }]
      },
      { type: 'content', title: '1. Résumé exécutif',
        sections: [{ text: doc.description }, { subheading: '1.1 Points clés', bullets: s.rcaBullets }, { subheading: '1.2 Contexte', text: `Incident détecté le ${doc.date} sur le service ${s.service}. Durée totale : ${s.duration}. Impact : ${s.impact}.` }]
      },
      { type: 'content', title: '2. Description de l\'incident',
        sections: [{ heading: '2.1 Périmètre', text: `L\'incident a affecté le service ${s.service} (catégorie : ${doc.category}) avec une sévérité ${s.sev}. Période : ${s.period}.` }, { heading: '2.2 Symptômes observés', bullets: [`Impact utilisateur : ${s.impact}`, `Latence mesurée : ${s.latency}`, `Taux d\'erreur : ${s.errors}`, `Uptime période : ${s.uptime}`, `Tags associés : ${doc.tags.join(', ')}`] }, { heading: '2.3 Services affectés', text: `Service principal : ${s.service}. Tous les services dépendants ont été impactés en cascade pendant la durée de l\'incident.` }]
      },
      { type: 'table', title: '3. Chronologie de l\'incident',
        sections: [{ heading: '3.1 Timeline détaillée', table: { headers: ['Heure', 'Événement', 'Responsable', 'Action'], rows: [['T+0 min', 'Détection de l\'anomalie par monitoring', 'Système', 'Alerte déclenchée'], ['T+5 min', 'Confirmation de l\'incident et ouverture ticket', 'On-call', 'Ticket P' + s.sev.slice(1) + ' créé'], ['T+15 min', 'Diagnostic de la cause racine', 'Équipe SRE', 'Investigation en cours'], ['T+' + s.duration, 'Résolution et retour à la normale', 'Équipe SRE', 'Incident clos']] } }, { heading: '3.2 Durée totale', metric: [{ label: 'MTTD', value: '5 min' }, { label: 'MTTR', value: s.duration }, { label: 'Impact', value: s.impact }] }]
      },
      { type: 'chart', title: '4. Analyse d\'impact',
        sections: [{ heading: '4.1 Métriques pendant l\'incident', metric: [{ label: 'Uptime', value: s.uptime, note: 'Pendant incident' }, { label: 'Latence', value: s.latency, note: 'Pic mesuré' }, { label: 'Taux d\'erreur', value: s.errors, note: 'Pendant incident' }, { label: 'Durée', value: s.duration, note: 'MTTR' }] }, { heading: '4.2 Utilisateurs impactés', text: `Impact direct : ${s.impact}. Le service ${s.service} est utilisé par l\'ensemble des utilisateurs actifs de la plateforme DXC Copilot.` }]
      },
      { type: 'content', title: '5. Analyse cause racine (RCA)',
        sections: [{ heading: '5.1 Cause principale', text: s.rca }, { heading: '5.2 Facteurs contributeurs', bullets: s.rcaBullets }, { heading: '5.3 Catégorie de cause', text: `Cette défaillance appartient à la catégorie "${doc.category}". Elle est classée ${doc.severity} selon la matrice d\'impact × urgence de DXC Technology.` }]
      },
      { type: 'content', title: '6. Mesures de résolution',
        sections: [{ heading: '6.1 Actions correctives immédiates', numbered: s.steps }, { heading: '6.2 Équipe mobilisée', table: { headers: ['Rôle', 'Action', 'Durée'], rows: [['On-call SRE', 'Diagnostic initial et escalade', '15 min'], ['Tech Lead', 'Validation de la cause racine', '10 min'], ['Ops Engineer', 'Déploiement du correctif', '20 min'], ['QA Engineer', 'Validation et smoke tests', '10 min']] } }]
      },
      { type: 'table', title: '7. Tests et validation',
        sections: [{ heading: '7.1 Tests de non-régression', table: { headers: ['Test', 'Résultat', 'Commentaire'], rows: [['Smoke tests API', '✔ Passé', 'Tous endpoints répondent'], ['Test de charge 2× normal', '✔ Passé', 'Aucune dégradation'], ['Test de failover', '✔ Passé', 'Bascule en < 5s'], ['Monitoring 30 min post-fix', '✔ Stable', 'Métriques normales']] } }, { heading: '7.2 Critères de clôture', bullets: ['Latence revenue sous le SLO (< 400ms)', 'Taux d\'erreur < 0.1%', 'Uptime > 99.9% sur 30 min post-correction', 'Validation fonctionnelle complète'] }]
      },
      { type: 'chart', title: '8. Indicateurs post-incident',
        sections: [{ heading: '8.1 Métriques après résolution', metric: [{ label: 'Latence moyenne', value: '< 400 ms', note: '✔ SLO respecté' }, { label: 'Uptime 24h post', value: '100%', note: '✔ Stable' }, { label: 'Taux d\'erreur', value: '< 0.1%', note: '✔ Normal' }, { label: 'Utilisateurs impactés', value: '0', note: 'Retour à la normale' }] }, { heading: '8.2 Comparaison avant / après', table: { headers: ['Métrique', 'Pendant incident', 'Post-résolution', 'SLO'], rows: [['Latence', s.latency, '< 400 ms', '< 500 ms'], ['Erreurs', s.errors, '< 0.1%', '< 0.5%'], ['Uptime', s.uptime, '100%', '≥ 99.9%']] } }]
      },
      { type: 'content', title: '9. Recommandations et prévention',
        sections: [{ heading: '9.1 Mesures préventives', bullets: s.prevention }, { heading: '9.2 Plan d\'action', table: { headers: ['Action', 'Priorité', 'Délai', 'Responsable'], rows: s.prevention.map((p: string, i: number) => [p.slice(0, 40) + '...', i < 2 ? 'Haute' : 'Moyenne', i < 2 ? '1 semaine' : '1 mois', 'Équipe SRE']) } }]
      },
      { type: 'conclusion', title: '10. Conclusion et bilan',
        sections: [{ text: s.conclusion }, { heading: '10.1 Bilan de l\'incident', table: { headers: ['Critère', 'Objectif', 'Résultat', 'Statut'], rows: [['Durée résolution', '< 60 min', s.duration, s.duration.includes('cours') ? '⏳ En cours' : '✔ Atteint'], ['Perte de données', '0', '0', '✔ Atteint'], ['Communication', '< 10 min', '< 5 min', '✔ Atteint'], ['Post-mortem', 'Sous 48h', 'Réalisé', '✔ Atteint']] } }, { highlight: `Document généré automatiquement par DXC Copilot IA — Incident #${doc.id} — ${doc.date} — Confidentiel` }]
      }
    ];
  }

  previousPage(): void {
    if (this.currentPage > 1) this.currentPage--;
  }

  nextPage(): void {
    if (this.currentPage < this.totalPages) this.currentPage++;
  }

  goToPage(n: number): void {
    if (n >= 1 && n <= this.totalPages) this.currentPage = n;
  }

  zoomIn(): void {
    if (this.zoomLevel < 200) this.zoomLevel += 25;
  }

  zoomOut(): void {
    if (this.zoomLevel > 50) this.zoomLevel -= 25;
  }

  downloadDocument(): void {
    const doc = this.selectedDoc;
    if (!doc) return;
    const lines = [
      `# ${doc.title}`,
      `Catégorie: ${doc.category} | Sévérité: ${doc.severity} | Statut: ${doc.status}`,
      `Date: ${doc.date} | Pages: ${doc.pages}`,
      '',
      doc.description,
      '',
      `Source: ${doc.generatedFrom}`,
      `Tags: ${doc.tags.join(', ')}`
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${doc.title.replace(/[^a-z0-9]/gi, '_')}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  printDocument(): void {
    window.print();
  }

}