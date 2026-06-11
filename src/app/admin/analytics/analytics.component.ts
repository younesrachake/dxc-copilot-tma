import { Component, OnInit } from '@angular/core';
import { NgFor, NgIf, DecimalPipe, PercentPipe } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService, RagAnalyticsResponse } from '../../services/api.service';

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [NgFor, NgIf, DecimalPipe, PercentPipe],
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

  constructor(private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.refreshData();
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
