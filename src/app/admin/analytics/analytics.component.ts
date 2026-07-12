import { Component, OnInit } from '@angular/core';
import { NgFor, NgIf, DecimalPipe, PercentPipe, SlicePipe } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService, RagAnalyticsResponse } from '../../services/api.service';

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [NgFor, NgIf, DecimalPipe, PercentPipe, SlicePipe],
  templateUrl: './analytics.component.html',
  styleUrl: './analytics.component.scss'
})
export class AnalyticsComponent implements OnInit {
  metrics: any[] = [];
  chartData: any[] = [];
  topFeatures: any[] = [];
  isLoading = false;

  // Real RAG analytics
  ragStats: RagAnalyticsResponse | null = null;
  ragLoading = false;

  // AI Insights (embeddings-driven analysis)
  gaps: any = null;
  gapsLoading = false;
  clusters: any = null;
  clustersLoading = false;
  thresholds: any = null;
  thresholdsLoading = false;
  applyingThresholds = false;
  insightMessage = '';

  constructor(private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.refreshData();
    this.loadInsights(false);
  }

  loadInsights(refresh: boolean): void {
    this.gapsLoading = true;
    this.clustersLoading = true;
    this.thresholdsLoading = true;
    this.api.getKnowledgeGaps(refresh).subscribe({
      next: (r) => { this.gaps = r; this.gapsLoading = false; },
      error: () => { this.gapsLoading = false; }
    });
    this.api.getIncidentClusters(30, refresh).subscribe({
      next: (r) => { this.clusters = r; this.clustersLoading = false; },
      error: () => { this.clustersLoading = false; }
    });
    this.api.getRoutingThresholds(refresh).subscribe({
      next: (r) => { this.thresholds = r; this.thresholdsLoading = false; },
      error: () => { this.thresholdsLoading = false; }
    });
  }

  applyRecommendedThresholds(): void {
    const rec = this.thresholds?.recommendation;
    if (!rec || rec.status !== 'ok' || this.applyingThresholds) return;
    this.applyingThresholds = true;
    this.api.applyRoutingThresholds({
      t_low: rec.recommended_t_low,
      t_high: rec.recommended_t_high
    }).subscribe({
      next: (r) => {
        this.applyingThresholds = false;
        this.insightMessage = '✅ Seuils appliqués — le routage RAG utilise les nouvelles valeurs.';
        if (this.thresholds) this.thresholds.current = r.settings;
        setTimeout(() => this.insightMessage = '', 4000);
      },
      error: (e) => {
        this.applyingThresholds = false;
        this.insightMessage = `⚠️ ${e.message}`;
        setTimeout(() => this.insightMessage = '', 4000);
      }
    });
  }

  getMaxRequests(): number {
    if (!this.chartData.length) return 1;
    return Math.max(...this.chartData.map((d: any) => d.requests || d.sessions || 0)) || 1;
  }

  getMaxSessions(): number {
    if (!this.chartData.length) return 1;
    return Math.max(...this.chartData.map((d: any) => d.sessions || 0)) || 1;
  }

  /** Bar height % for routing chart (kb_primary + kb_hint + groq_only) */
  routingBarHeight(value: number): number {
    if (!this.ragStats) return 0;
    const total = this.ragStats.routing_breakdown.kb_primary
      + this.ragStats.routing_breakdown.kb_hint
      + this.ragStats.routing_breakdown.groq_only;
    return total > 0 ? Math.round((value / total) * 100) : 0;
  }

  goBack(): void {
    this.router.navigate(['/admin']);
  }

  exportData(): void {
    const rows = ['Métrique,Valeur,Changement', ...this.metrics.map(m => `${m.label},${m.value},${m.change}`)];
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = 'analytics.csv'; a.click();
  }

  refreshData(): void {
    this.isLoading = true;
    this.ragLoading = true;
    this.api.getAnalytics().subscribe({
      next: (data) => {
        this.metrics = data.metrics || [];
        this.chartData = data.chart_data || [];
        this.topFeatures = data.top_features || [];
        this.isLoading = false;
      },
      error: () => { this.isLoading = false; }
    });
    this.api.getRagAnalytics().subscribe({
      next: (data) => { this.ragStats = data; this.ragLoading = false; },
      error: () => { this.ragLoading = false; }
    });
  }
}
