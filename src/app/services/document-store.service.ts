import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { IncidentDoc } from '../document-viewer/document-viewer.component';

const SEED_DOCS: IncidentDoc[] = [
  { id: 1, title: 'Guide d\'incident — Saturation mémoire API Gateway', description: 'L\'API Gateway a atteint 98% d\'utilisation mémoire après un pic de trafic non anticipé. Ce guide documente le diagnostic, la résolution et les mesures préventives.', category: 'Infrastructure', severity: 'P2', status: 'Résolu', date: '08/10/2024', size: '1.8 MB', pages: 12, generatedFrom: 'Session : Analyse de perfor...', tags: ['memory', 'gateway', 'autoscaling'] },
  { id: 2, title: 'Guide d\'incident — Timeout LLM Service', description: 'Le service LLM a produit des timeouts répétés lors de l\'inférence de modèles volumineux. Le guide couvre le rollback de version et la mise en place de circuit breakers.', category: 'Performance', severity: 'P2', status: 'Résolu', date: '15/11/2024', size: '2.1 MB', pages: 12, generatedFrom: 'Session : Revue de code', tags: ['llm', 'timeout', 'circuit-breaker'] },
  { id: 3, title: 'Guide d\'incident — Pic de charge nocturne', description: 'Un pic inattendu de requêtes entre 02h et 04h a saturé les workers. Ce guide documente la mise en place du scaling automatique basé sur des métriques temporelles.', category: 'Infrastructure', severity: 'P2', status: 'Résolu', date: '03/12/2024', size: '1.5 MB', pages: 12, generatedFrom: 'Session : Optimisation SQL', tags: ['scaling', 'workers', 'cron'] },
  { id: 4, title: 'Guide d\'incident — Dégradation Auth Service', description: 'Le service d\'authentification a répondu avec des latences anormales (>800ms) suite à une mauvaise configuration du cache Redis. Résolution par reconfiguration TTL.', category: 'Sécurité', severity: 'P3', status: 'Résolu', date: '22/11/2024', size: '1.2 MB', pages: 12, generatedFrom: 'Session : Documentation API', tags: ['auth', 'redis', 'latency'] },
  { id: 5, title: 'Guide d\'incident — Erreurs 502 Bad Gateway', description: 'Des erreurs 502 intermittentes ont impacté 12% des requêtes pendant 45 minutes. Ce guide documente la correction du load balancer et les nouveaux health checks.', category: 'Disponibilité', severity: 'P2', status: 'En cours', date: '02/01/2025', size: '1.9 MB', pages: 12, generatedFrom: 'Session : Déploiement CI/CD', tags: ['502', 'load-balancer', 'health-check'] },
  { id: 6, title: 'Guide d\'incident — Latence anormale Q1 2025', description: 'Une dégradation progressive de la latence de réponse a été détectée en janvier 2025. Analyse des causes liées à la fragmentation des index de base de données.', category: 'Performance', severity: 'P3', status: 'En cours', date: '14/01/2025', size: '2.3 MB', pages: 12, generatedFrom: 'Session : Analyse de perfor...', tags: ['latency', 'database', 'indexing'] },
  { id: 7, title: 'Guide d\'incident — Fuite mémoire Queue Worker', description: 'Une fuite mémoire critique dans le service Queue Worker a provoqué des redémarrages en boucle. Guide de patch d\'urgence et refactoring du gestionnaire de messages.', category: 'Infrastructure', severity: 'P1', status: 'Résolu', date: '08/10/2024', size: '2.7 MB', pages: 12, generatedFrom: 'Session : Revue de code', tags: ['memory-leak', 'queue', 'worker'] },
  { id: 8, title: 'Guide d\'incident — Interruption base de données', description: 'Une interruption de 18 minutes de la base de données principale due à une migration mal planifiée. Ce guide établit les procédures de migration sans downtime.', category: 'Disponibilité', severity: 'P1', status: 'Résolu', date: '25/09/2024', size: '3.1 MB', pages: 12, generatedFrom: 'Session : Optimisation SQL', tags: ['database', 'migration', 'downtime'] },
  { id: 9, title: 'Guide d\'incident — Tentatives d\'accès suspectes', description: '1 842 tentatives d\'accès non autorisées détectées en provenance de 3 IP distinctes. Guide de durcissement du pare-feu et mise en place du rate limiting.', category: 'Sécurité', severity: 'P2', status: 'Résolu', date: '18/11/2024', size: '1.6 MB', pages: 12, generatedFrom: 'Session : Documentation API', tags: ['security', 'firewall', 'rate-limiting'] },
  { id: 10, title: 'Guide d\'incident — Dépassement quota API externe', description: 'Le quota journalier de l\'API externe du fournisseur LLM a été dépassé suite à une boucle de retry non bornée. Guide d\'implémentation de backoff exponentiel.', category: 'Performance', severity: 'P3', status: 'Résolu', date: '30/10/2024', size: '1.4 MB', pages: 12, generatedFrom: 'Session : Optimisation SQL', tags: ['api-quota', 'retry', 'backoff'] },
  { id: 11, title: 'Guide d\'incident — Crash Notification Service', description: 'Le microservice de notifications a crashé après une mise à jour de dépendances incompatible. Guide de rollback et stratégie de test des dépendances avant déploiement.', category: 'Infrastructure', severity: 'P3', status: 'Résolu', date: '22/11/2024', size: '1.3 MB', pages: 12, generatedFrom: 'Session : Déploiement CI/CD', tags: ['notification', 'dependency', 'rollback'] },
  { id: 12, title: 'Guide d\'incident — Corruption cache Redis', description: 'Des données corrompues dans le cache Redis ont causé des réponses incohérentes pour 8% des utilisateurs. Guide de purge sélective et stratégie de validation du cache.', category: 'Infrastructure', severity: 'P2', status: 'Ouvert', date: '05/01/2025', size: '1.7 MB', pages: 12, generatedFrom: 'Session : Revue de code', tags: ['redis', 'cache', 'corruption'] },
];

@Injectable({ providedIn: 'root' })
export class DocumentStoreService {
  private _docs$ = new BehaviorSubject<IncidentDoc[]>([...SEED_DOCS]);
  readonly docs$ = this._docs$.asObservable();

  get docs(): IncidentDoc[] { return this._docs$.getValue(); }

  /** Replace the whole list (called after API load) */
  setDocs(docs: IncidentDoc[]): void {
    // Merge API docs with any runtime-added docs (id > 1000 = added from chat)
    const chatAdded = this._docs$.getValue().filter(d => d.id > 1000);
    this._docs$.next([...chatAdded, ...docs]);
  }

  /** Add a single document and return it (called from chat / RG2) */
  addDocument(partial: Partial<IncidentDoc> & { content?: string }): IncidentDoc {
    const doc: IncidentDoc = {
      id: Date.now(),
      title: partial.title || 'Guide d\'incident',
      description: partial.description || '',
      category: partial.category || 'Infrastructure',
      severity: partial.severity || 'P2',
      status: partial.status || 'Ouvert',
      date: new Date().toLocaleDateString('fr-FR'),
      size: '—',
      pages: 12,
      generatedFrom: partial.generatedFrom || 'Chat DXC Copilot',
      tags: partial.tags || [],
      content: partial.content
    };
    this._docs$.next([doc, ...this.docs]);
    return doc;
  }
}
