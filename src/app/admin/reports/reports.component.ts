import { Component, OnInit } from '@angular/core';
import { NgFor, NgIf, NgClass, DecimalPipe } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-reports',
  standalone: true,
  imports: [NgFor, NgIf, NgClass, DecimalPipe],
  templateUrl: './reports.component.html',
  styleUrl: './reports.component.scss'
})
export class ReportsComponent implements OnInit {
  selectedReport: string | null = null;
  isGenerating = false;
  generationProgress = 0;
  isLoading = false;

  reports: any[] = [];

  reportTemplates = [
    { key: 'mensuel', name: 'Rapport mensuel', description: 'Statistiques mensuelles complètes', icon: '📊' },
    { key: 'trimestriel', name: 'Rapport trimestriel', description: 'Analyse trimestrielle détaillée', icon: '📈' },
    { key: 'performance', name: 'Rapport de performance', description: 'Analyse des performances système', icon: '⚡' },
    { key: 'utilisateurs', name: 'Rapport utilisateurs', description: 'Activité et engagement utilisateurs', icon: '👥' }
  ];

  mensuelData = {
    period: 'Mars 2026',
    kpis: [
      { label: 'Sessions totales', value: '14 832', change: '+8.4%', up: true },
      { label: 'Nouveaux utilisateurs', value: '342', change: '+12.1%', up: true },
      { label: 'Messages traités', value: '87 504', change: '+5.2%', up: true },
      { label: 'Taux d\'erreur', value: '0.3%', change: '-0.1%', up: false }
    ],
    dailyData: [
      { day: '01', sessions: 450 }, { day: '05', sessions: 520 }, { day: '10', sessions: 480 },
      { day: '15', sessions: 610 }, { day: '20', sessions: 580 }, { day: '25', sessions: 540 },
      { day: '31', sessions: 495 }
    ],
    topFeatures: [
      { name: 'Génération de code', usage: 38, pct: 38 },
      { name: 'Analyse de documents', usage: 27, pct: 27 },
      { name: 'Résumé automatique', usage: 19, pct: 19 },
      { name: 'Traduction', usage: 16, pct: 16 }
    ]
  };

  trimestrielData = {
    period: 'Q1 2026 (Jan - Mar)',
    months: [
      { name: 'Janvier', sessions: 12400, users: 280, messages: 72000 },
      { name: 'Février', sessions: 13100, users: 310, messages: 79500 },
      { name: 'Mars', sessions: 14832, users: 342, messages: 87504 }
    ],
    kpis: [
      { label: 'Sessions Q1', value: '40 332', change: '+18.2%', up: true },
      { label: 'Utilisateurs Q1', value: '932', change: '+22.4%', up: true },
      { label: 'Messages Q1', value: '239 004', change: '+14.7%', up: true },
      { label: 'Satisfaction', value: '94.2%', change: '+1.8%', up: true }
    ],
    comparison: [
      { label: 'Sessions', q0: 34000, q1: 40332, pct: 18 },
      { label: 'Utilisateurs', q0: 762, q1: 932, pct: 22 },
      { label: 'Messages', q0: 208000, q1: 239004, pct: 15 }
    ]
  };

  performanceData = {
    period: 'Avril 2026',
    kpis: [
      { label: 'Temps de réponse moyen', value: '142 ms', change: '-12ms', up: false },
      { label: 'Disponibilité', value: '99.97%', change: '+0.02%', up: true },
      { label: 'Requêtes/sec', value: '284', change: '+32', up: true },
      { label: 'Erreurs 5xx', value: '0.03%', change: '-0.01%', up: false }
    ],
    services: [
      { name: 'API Gateway', uptime: 99.99, latency: 45, status: 'Opérationnel' },
      { name: 'LLM Service', uptime: 99.95, latency: 210, status: 'Opérationnel' },
      { name: 'Auth Service', uptime: 100, latency: 12, status: 'Opérationnel' },
      { name: 'Storage Service', uptime: 99.98, latency: 28, status: 'Opérationnel' },
      { name: 'Queue Worker', uptime: 99.91, latency: 5, status: 'Dégradé' }
    ],
    latencyBuckets: [
      { range: '< 100ms', pct: 42 },
      { range: '100-200ms', pct: 35 },
      { range: '200-500ms', pct: 18 },
      { range: '> 500ms', pct: 5 }
    ]
  };

  utilisateursData = {
    period: 'Avril 2026',
    kpis: [
      { label: 'Utilisateurs actifs', value: '1 247', change: '+9.3%', up: true },
      { label: 'Nouvelles inscriptions', value: '89', change: '+14.2%', up: true },
      { label: 'Rétention 30j', value: '76.4%', change: '+2.1%', up: true },
      { label: 'Sessions/utilisateur', value: '11.9', change: '+0.8', up: true }
    ],
    topUsers: [
      { name: 'Alice Martin', dept: 'R&D', sessions: 142, messages: 1820 },
      { name: 'Bob Dupont', dept: 'IT', sessions: 128, messages: 1540 },
      { name: 'Claire Leclerc', dept: 'Finance', sessions: 115, messages: 1390 },
      { name: 'David Morin', dept: 'RH', sessions: 98, messages: 1120 },
      { name: 'Emma Bernard', dept: 'Marketing', sessions: 87, messages: 980 }
    ],
    byDept: [
      { dept: 'R&D', users: 312, pct: 25 },
      { dept: 'IT', users: 248, pct: 20 },
      { dept: 'Finance', users: 187, pct: 15 },
      { dept: 'Marketing', users: 150, pct: 12 },
      { dept: 'RH', users: 125, pct: 10 },
      { dept: 'Autres', users: 225, pct: 18 }
    ]
  };

  constructor(private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.loadReports();
  }

  loadReports(): void {
    this.isLoading = true;
    this.api.getReportSummary().subscribe({
      next: (data) => {
        this.reports = data.reports || [
          { id: 1, name: 'Rapport mensuel - Mars 2026', type: 'Mensuel', date: '01/04/2026', size: '2.4 MB', status: 'Disponible' },
          { id: 2, name: 'Rapport trimestriel Q1 2026', type: 'Trimestriel', date: '01/04/2026', size: '5.8 MB', status: 'Disponible' },
          { id: 3, name: 'Analyse de performance - Avril', type: 'Performance', date: '05/04/2026', size: '1.2 MB', status: 'En cours' },
          { id: 4, name: 'Rapport utilisateurs actifs', type: 'Utilisateurs', date: '05/04/2026', size: '850 KB', status: 'Disponible' },
          { id: 5, name: 'Rapport de sécurité - Mars 2026', type: 'Sécurité', date: '01/04/2026', size: '3.1 MB', status: 'Disponible' }
        ];
        this.isLoading = false;
      },
      error: () => {
        this.reports = [
          { id: 1, name: 'Rapport mensuel - Mars 2026', type: 'Mensuel', date: '01/04/2026', size: '2.4 MB', status: 'Disponible' },
          { id: 2, name: 'Rapport trimestriel Q1 2026', type: 'Trimestriel', date: '01/04/2026', size: '5.8 MB', status: 'Disponible' },
          { id: 3, name: 'Analyse de performance - Avril', type: 'Performance', date: '05/04/2026', size: '1.2 MB', status: 'En cours' },
          { id: 4, name: 'Rapport utilisateurs actifs', type: 'Utilisateurs', date: '05/04/2026', size: '850 KB', status: 'Disponible' },
          { id: 5, name: 'Rapport de sécurité - Mars 2026', type: 'Sécurité', date: '01/04/2026', size: '3.1 MB', status: 'Disponible' }
        ];
        this.isLoading = false;
      }
    });
  }

  generateReport(template: any): void {
    this.selectedReport = template.key;
    this.isGenerating = true;
    this.generationProgress = 0;

    const progressInterval = setInterval(() => {
      if (this.generationProgress < 90) {
        this.generationProgress += Math.floor(Math.random() * 8) + 3;
        if (this.generationProgress > 90) this.generationProgress = 90;
      }
    }, 300);

    this.api.getReportData(template.key).subscribe({
      next: (data: any) => {
        clearInterval(progressInterval);
        if (data) Object.assign((this as any)[template.key + 'Data'], data);
        this.generationProgress = 100;
        this.isGenerating = false;
      },
      error: () => {
        clearInterval(progressInterval);
        this.generationProgress = 100;
        this.isGenerating = false;
      }
    });
  }

  closeReport(): void {
    this.selectedReport = null;
  }

  getMaxSessions(): number {
    return Math.max(...this.mensuelData.dailyData.map(d => d.sessions));
  }

  getMaxMonthSessions(): number {
    return Math.max(...this.trimestrielData.months.map(m => m.sessions));
  }

  exportReport(): void {
    if (!this.selectedReport) return;
    const data = (this as any)[this.selectedReport + 'Data'];
    if (!data) return;
    const rows: string[] = [`Rapport: ${data.period || this.selectedReport}`];
    if (data.kpis) {
      rows.push('', 'KPIs', 'Indicateur,Valeur');
      data.kpis.forEach((k: any) => rows.push(`${k.label},${k.value}`));
    }
    if (data.topUsers) {
      rows.push('', 'Top Utilisateurs', 'Nom,Département,Sessions');
      data.topUsers.forEach((u: any) => rows.push(`${u.name},${u.dept},${u.sessions}`));
    }
    if (data.byDept) {
      rows.push('', 'Par Département', 'Département,Utilisateurs,%');
      data.byDept.forEach((d: any) => rows.push(`${d.dept},${d.users},${d.pct}%`));
    }
    if (data.months) {
      rows.push('', 'Par Mois', 'Mois,Sessions,Utilisateurs,Messages');
      data.months.forEach((m: any) => rows.push(`${m.name},${m.sessions},${m.users},${m.messages}`));
    }
    const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `rapport-${this.selectedReport}-${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
  }

  downloadReport(report: any): void {
    const rows = [
      `Rapport: ${report.name}`,
      `Type: ${report.type} | Date: ${report.date} | Statut: ${report.status} | Taille: ${report.size}`
    ];
    const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${report.name.replace(/[^a-z0-9]/gi, '_')}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  viewReport(report: any): void {
    this.router.navigate(['/viewer']);
  }

  deleteReport(report: any): void {
    if (confirm(`Supprimer "${report.name}" ?`)) {
      this.reports = this.reports.filter(r => r.id !== report.id);
    }
  }

  goBack(): void {
    this.router.navigate(['/admin']);
  }
}
