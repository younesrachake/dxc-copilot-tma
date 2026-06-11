import { Component, OnInit } from '@angular/core';
import { NgFor, NgIf, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-system-logs',
  standalone: true,
  imports: [NgFor, NgIf, DatePipe, FormsModule],
  templateUrl: './system-logs.component.html',
  styleUrl: './system-logs.component.scss'
})
export class SystemLogsComponent implements OnInit {
  logs: any[] = [];
  filteredLogs: any[] = [];
  selectedLevel: string = 'all';
  selectedService: string = 'all';
  searchTerm: string = '';
  isLoading = false;

  constructor(private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.refreshLogs();
  }

  filterLogs(): void {
    this.filteredLogs = this.logs.filter(log => {
      const matchesLevel = this.selectedLevel === 'all' || log.level === this.selectedLevel;
      const matchesService = this.selectedService === 'all' || log.service === this.selectedService;
      const matchesSearch = log.message.toLowerCase().includes(this.searchTerm.toLowerCase()) ||
                           (log.user || '').toLowerCase().includes(this.searchTerm.toLowerCase());
      return matchesLevel && matchesService && matchesSearch;
    });
  }

  clearLogs(): void {
    if (confirm('Effacer tous les logs ?')) {
      this.api.clearLogs().subscribe({
        next: () => { this.logs = []; this.filteredLogs = []; }
      });
    }
  }

  exportLogs(): void {
    const rows = ['Timestamp,Level,Service,Message,User',
      ...this.filteredLogs.map(l => `${l.timestamp},${l.level},${l.service},${l.message},${l.user || ''}`)];
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = 'system-logs.csv'; a.click();
  }

  refreshLogs(): void {
    this.isLoading = true;
    const level = this.selectedLevel !== 'all' ? this.selectedLevel : undefined;
    const service = this.selectedService !== 'all' ? this.selectedService : undefined;
    this.api.getLogs(100, level, service).subscribe({
      next: (data) => {
        this.logs = (data.logs || []).map((l: any, i: number) => ({
          id: i + 1,
          timestamp: new Date(l.timestamp),
          level: l.level,
          service: l.service,
          message: l.message,
          user: l.user || 'system'
        }));
        this.filteredLogs = [...this.logs];
        this.isLoading = false;
      },
      error: () => { this.isLoading = false; }
    });
  }

  goBack(): void {
    this.router.navigate(['/admin']);
  }
}
