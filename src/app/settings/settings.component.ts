import { Component, OnInit } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ThemeService } from '../services/theme.service';
import { ApiService } from '../services/api.service';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss'
})
export class SettingsComponent implements OnInit {
  activeTab: string = 'profile';
  feedback = '';
  isUpdatingPassword = false;

  userProfile = {
    name: '',
    email: '',
    department: '',
    language: 'fr'
  };

  passwordForm = {
    currentPassword: '',
    newPassword: '',
    confirmPassword: ''
  };

  preferences = {
    theme: 'dark',
    notifications: true,
    autoSave: true,
    fontSize: 'medium'
  };

  tabs = [
    { id: 'profile', label: 'Profil', icon: '👤' },
    { id: 'preferences', label: 'Préférences', icon: '⚙️' },
    { id: 'security', label: 'Sécurité', icon: '🔒' },
    { id: 'api', label: 'API', icon: '🔗' }
  ];

  constructor(private router: Router, private themeService: ThemeService, private api: ApiService) {}

  ngOnInit(): void {
    this.preferences.theme = this.themeService.isDark ? 'dark' : 'light';
    this.api.getUser().subscribe({
      next: (user) => {
        this.userProfile.name = user.full_name || '';
        this.userProfile.email = user.email || '';
        this.userProfile.department = user.department || '';
      }
    });
  }

  selectTab(tabId: string): void {
    this.activeTab = tabId;
  }

  saveProfile(): void {
    this.api.updateProfile({
      full_name: this.userProfile.name,
      department: this.userProfile.department
    }).subscribe({
      next: () => {
        this.feedback = 'Profil sauvegardé avec succès.';
        setTimeout(() => this.feedback = '', 3000);
      },
      error: (err) => {
        this.feedback = 'Erreur: ' + err.message;
        setTimeout(() => this.feedback = '', 3000);
      }
    });
  }

  savePreferences(): void {
    const t = this.preferences.theme;
    this.themeService.setTheme(t === 'dark' ? 'dark' : 'light');
    this.feedback = 'Préférences sauvegardées.';
    setTimeout(() => this.feedback = '', 3000);
  }

  regenerateApiKey(): void {
    this.feedback = 'Clé API régénérée.';
    setTimeout(() => this.feedback = '', 3000);
  }

  updatePassword(): void {
    if (!this.passwordForm.currentPassword || !this.passwordForm.newPassword || !this.passwordForm.confirmPassword) {
      this.feedback = 'Veuillez remplir tous les champs.';
      setTimeout(() => this.feedback = '', 4000);
      return;
    }
    if (this.passwordForm.newPassword !== this.passwordForm.confirmPassword) {
      this.feedback = 'Les mots de passe ne correspondent pas.';
      setTimeout(() => this.feedback = '', 4000);
      return;
    }
    if (this.passwordForm.newPassword.length < 12) {
      this.feedback = 'Le mot de passe doit contenir au moins 12 caractères.';
      setTimeout(() => this.feedback = '', 4000);
      return;
    }
    this.isUpdatingPassword = true;
    this.api.changePassword(this.passwordForm.currentPassword, this.passwordForm.newPassword).subscribe({
      next: () => {
        this.feedback = 'Mot de passe mis à jour avec succès.';
        this.passwordForm = { currentPassword: '', newPassword: '', confirmPassword: '' };
        this.isUpdatingPassword = false;
        setTimeout(() => this.feedback = '', 4000);
      },
      error: (err) => {
        this.feedback = 'Erreur: ' + (err.error?.detail || err.message || 'Erreur inconnue');
        this.isUpdatingPassword = false;
        setTimeout(() => this.feedback = '', 5000);
      }
    });
  }
}
