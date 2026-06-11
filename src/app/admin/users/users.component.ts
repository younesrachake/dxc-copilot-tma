import { Component, OnInit } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../../services/api.service';

interface User {
  id: number;
  name: string;
  email: string;
  role: 'Admin' | 'Utilisateur' | 'Viewer';
  status: 'Actif' | 'Inactif';
  lastLogin: string;
}

@Component({
  selector: 'app-users',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule],
  templateUrl: './users.component.html',
  styleUrl: './users.component.scss'
})

export class UsersComponent implements OnInit {
  users: User[] = [];

  searchTerm = '';
  selectedRole = 'all';
  isLoading = false;

  // ── Add modal ───────────────────────────────────────────────────
  showAddModal = false;
  newUserForm: Partial<User> & { password: string; confirmPassword: string } = {
    name: '', email: '', role: 'Utilisateur', status: 'Actif', password: '', confirmPassword: ''
  };
  addError = '';

  deletingUserId: number | null = null;

  // ── Edit modal ──────────────────────────────────────────────────
  showEditModal = false;
  editUserForm: Partial<User> = {};
  editingUserId: number | null = null;

  constructor(private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.loadUsers();
  }

  private mapRole(role: string): User['role'] {
    if (role === 'admin') return 'Admin';
    if (role === 'viewer') return 'Viewer';
    return 'Utilisateur';
  }

  private mapStatus(status: string): User['status'] {
    return status === 'active' ? 'Actif' : 'Inactif';
  }

  loadUsers(): void {
    this.isLoading = true;
    this.api.getUsers().subscribe({
      next: (data) => {
        this.users = data.map(u => ({
          id: u.id,
          name: u.name || u.email,
          email: u.email,
          role: this.mapRole(u.role),
          status: this.mapStatus(u.status),
          lastLogin: u.last_login || '—'
        }));
        this.isLoading = false;
      },
      error: () => { this.isLoading = false; }
    });
  }

  get filteredUsers(): User[] {
    return this.users.filter(user => {
      const matchesSearch = user.name.toLowerCase().includes(this.searchTerm.toLowerCase()) ||
                            user.email.toLowerCase().includes(this.searchTerm.toLowerCase());
      const matchesRole = this.selectedRole === 'all' || user.role === this.selectedRole;
      return matchesSearch && matchesRole;
    });
  }

  // ── Add ─────────────────────────────────────────────────────────
  addUser(): void {
    this.newUserForm = { name: '', email: '', role: 'Utilisateur', status: 'Actif', password: '', confirmPassword: '' };
    this.addError = '';
    this.showAddModal = true;
  }

  closeAddModal(): void { this.showAddModal = false; }

  submitNewUser(): void {
    const { name, email, role, password, confirmPassword } = this.newUserForm;
    if (!name?.trim() || !email?.trim() || !password?.trim()) {
      this.addError = 'Nom, email et mot de passe sont obligatoires.';
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email!)) {
      this.addError = 'Adresse email invalide.';
      return;
    }
    if (password !== confirmPassword) {
      this.addError = 'Les mots de passe ne correspondent pas.';
      return;
    }
    const apiRole = role === 'Admin' ? 'admin' : role === 'Viewer' ? 'viewer' : 'user';
    this.api.createUser({ name: name!.trim(), email: email!.trim(), password: password!, role: apiRole }).subscribe({
      next: () => {
        this.showAddModal = false;
        this.loadUsers();
      },
      error: (err) => { this.addError = err.message; }
    });
  }

  // ── Edit ────────────────────────────────────────────────────────
  editUser(user: User): void {
    this.editingUserId = user.id;
    this.editUserForm = { ...user };
    this.showEditModal = true;
  }

  closeEditModal(): void { this.showEditModal = false; this.editingUserId = null; }

  submitEditUser(): void {
    if (!this.editingUserId) return;
    const apiRole = this.editUserForm.role === 'Admin' ? 'admin' : this.editUserForm.role === 'Viewer' ? 'viewer' : 'user';
    const apiStatus = this.editUserForm.status === 'Actif' ? 'active' : 'inactive';
    this.api.updateUser(this.editingUserId, {
      name: this.editUserForm.name,
      email: this.editUserForm.email,
      role: apiRole,
      status: apiStatus
    }).subscribe({
      next: () => { this.closeEditModal(); this.loadUsers(); },
      error: () => { this.closeEditModal(); }
    });
  }

  // ── Delete ──────────────────────────────────────────────────────
  deleteUser(user: User): void {
    if (this.deletingUserId === user.id) return;
    if (confirm(`Supprimer l'utilisateur "${user.name}" ?`)) {
      this.deletingUserId = user.id;
      this.api.deleteUser(user.id).subscribe({
        next: () => { this.deletingUserId = null; this.loadUsers(); },
        error: () => { this.deletingUserId = null; }
      });
    }
  }

  // ── Export ──────────────────────────────────────────────────────
  exportUsers(): void {
    const rows = ['Nom,Email,Rôle,Statut,Dernière connexion',
      ...this.users.map(u => `${u.name},${u.email},${u.role},${u.status},${u.lastLogin}`)];
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = 'utilisateurs.csv'; a.click();
  }

  goBack(): void { this.router.navigate(['/admin']); }
}
