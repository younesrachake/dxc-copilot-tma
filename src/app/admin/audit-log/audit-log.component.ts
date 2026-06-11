import { Component, OnInit } from '@angular/core';
import { NgFor, NgIf, DatePipe } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-audit-log',
  standalone: true,
  imports: [NgFor, NgIf, DatePipe],
  templateUrl: './audit-log.component.html',
  styleUrl: './audit-log.component.scss'
})
export class AuditLogComponent implements OnInit {
  items: any[] = [];
  total = 0;
  page = 1;
  pageSize = 50;
  isLoading = false;
  loadError = false;

  constructor(private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.loadPage();
  }

  loadPage(): void {
    this.isLoading = true;
    this.loadError = false;
    this.api.getAuditLog(this.page, this.pageSize).subscribe({
      next: (data) => {
        this.items = data.items || [];
        this.total = data.total || 0;
        this.isLoading = false;
      },
      error: () => { this.isLoading = false; this.loadError = true; }
    });
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.total / this.pageSize));
  }

  prevPage(): void {
    if (this.page > 1) { this.page--; this.loadPage(); }
  }

  nextPage(): void {
    if (this.page < this.totalPages) { this.page++; this.loadPage(); }
  }

  goBack(): void {
    this.router.navigate(['/admin']);
  }
}
