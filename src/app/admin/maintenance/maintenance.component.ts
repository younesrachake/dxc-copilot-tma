import { Component, OnInit } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-maintenance',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule],
  templateUrl: './maintenance.component.html',
  styleUrl: './maintenance.component.scss'
})
export class MaintenanceComponent implements OnInit {
  maintenanceTasks: any[] = [];
  systemHealth: any[] = [];
  isLoading = false;
  toastMessage = '';
  editingTaskId: number | null = null;
  editingTaskName = '';

  constructor(private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.loadHealth();
    this.loadTasks();
  }

  loadTasks(): void {
    this.api.getMaintenanceTasks().subscribe({
      next: (res: any) => { this.maintenanceTasks = res.tasks || []; },
      error: () => {}
    });
  }

  loadHealth(): void {
    this.isLoading = true;
    this.api.getMaintenanceHealth().subscribe({
      next: (data) => {
        this.systemHealth = data.components || [];
        this.isLoading = false;
      },
      error: () => { this.isLoading = false; }
    });
  }

  private toast(msg: string): void {
    this.toastMessage = msg;
    setTimeout(() => { this.toastMessage = ''; }, 3500);
  }

  runTask(task: any): void {
    this.api.runMaintenanceTask(task.id).subscribe({
      next: (res: any) => {
        task.lastRun = res.lastRun || new Date().toLocaleString('fr-FR');
        task.status = 'Active';
        this.toast('✅ ' + (res.message || 'Tâche exécutée.'));
      },
      error: (e: any) => this.toast('❌ Erreur : ' + e.message)
    });
  }

  startEditTask(task: any): void {
    this.editingTaskId = task.id;
    this.editingTaskName = task.name;
  }

  saveEditTask(task: any): void {
    const name = this.editingTaskName.trim();
    if (!name) { this.editingTaskId = null; return; }
    this.api.updateMaintenanceTask(task.id, { name }).subscribe({
      next: (updated: any) => { Object.assign(task, updated); task.name = name; },
      error: (e: any) => this.toast('❌ Erreur : ' + e.message)
    });
    this.editingTaskId = null;
  }

  cancelEditTask(): void { this.editingTaskId = null; }

  deleteTask(task: any): void {
    if (confirm(`Supprimer la tâche "${task.name}" ?`)) {
      this.api.deleteMaintenanceTask(task.id).subscribe({
        next: () => { this.maintenanceTasks = this.maintenanceTasks.filter(t => t.id !== task.id); },
        error: (e: any) => this.toast('❌ Erreur : ' + e.message)
      });
    }
  }

  runBackup(): void {
    this.api.runBackup().subscribe({
      next: (res) => this.toast('✅ ' + (res.message || 'Sauvegarde complétée avec succès!')),
      error: (err) => this.toast('❌ Erreur: ' + err.message)
    });
  }

  cleanCache(): void {
    this.api.cleanCache().subscribe({
      next: (res) => this.toast('✅ ' + (res.message || 'Cache nettoyé avec succès!')),
      error: (err) => this.toast('❌ Erreur: ' + err.message)
    });
  }

  optimizeDatabase(): void {
    this.api.optimizeDb().subscribe({
      next: (res) => this.toast('✅ ' + (res.message || 'Optimisation complétée!')),
      error: (err) => this.toast('❌ Erreur: ' + err.message)
    });
  }

  goBack(): void {
    this.router.navigate(['/admin']);
  }
}
