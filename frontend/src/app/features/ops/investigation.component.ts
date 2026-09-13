import { ChangeDetectionStrategy, Component, LOCALE_ID, signal } from '@angular/core';
import { CommonModule, registerLocaleData } from '@angular/common';
import localePt from '@angular/common/locales/pt';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

registerLocaleData(localePt);

interface DetectorEvent {
  id: string; customer: string; valor: string; tipo: string; timestamp: string;
  decididoEm: string; motivos: string[]; scoreFraude: number | null;
  modeloVersao: string; synthetic: boolean;
}
interface CaseItem { id: string; status: string; version: number; created_at: string; event: DetectorEvent; }
interface Procedure { id: string; title: string; body: string; digest: string; valid_from: string; }
interface Report {
  id: string;
  content: {
    proposal: { hipoteses: { texto: string; evidencias: string[] }[]; recomendacao: string; limitacoes: string[]; procedimentos: string[] };
    retrieval: { mode: string; documents: Procedure[] };
    generation: { mode: string; model: string | null; prompt_version: string };
    latency_ms: number;
  };
}
interface CaseDetail {
  id: string; status: string; version: number; snapshot_hash: string;
  snapshot: { event: DetectorEvent; summary: { previous_count_24h: number; previous_mean_24h: string | null; previous_total_24h: string; coverage: string; as_of: string }; limitations: string[] };
  reports: Report[];
  reviews: { subject: string; outcome: string; rationale: string; created_at: string }[];
  timeline: { id: string; action: string; subject: string; created_at: string }[];
}

@Component({
  selector: 'app-investigation', standalone: true, imports: [CommonModule, FormsModule, RouterLink],
  providers: [{ provide: LOCALE_ID, useValue: 'pt-BR' }],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './investigation.component.html', styleUrl: './investigation.component.css'
})
export class InvestigationComponent {
  readonly items = signal<CaseItem[]>([]);
  readonly selected = signal<CaseDetail | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly identity = signal<{ subject: string; scopes: string[] } | null>(null);
  token = '';
  outcome = 'INCONCLUSIVO';
  rationale = '';
  offset = 0;
  private activeToken = '';
  private readonly api = 'http://localhost:5010/api';

  private async request<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(this.api + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { Authorization: `Bearer ${this.activeToken}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(150000)
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : `Falha na solicitação (${response.status}).`);
    }
    return response.json() as Promise<T>;
  }

  private async run(action: () => Promise<void>): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true); this.error.set('');
    try { await action(); }
    catch (error) { this.error.set(error instanceof Error ? error.message : 'Não foi possível concluir.'); }
    finally { this.busy.set(false); }
  }

  async connect(): Promise<void> {
    await this.run(async () => {
      this.activeToken = this.token; this.token = '';
      this.identity.set(null); this.selected.set(null); this.items.set([]); this.offset = 0;
      this.identity.set(await this.request('/me'));
      await this.reload();
    });
  }

  disconnect(): void {
    this.activeToken = ''; this.token = ''; this.identity.set(null); this.selected.set(null); this.items.set([]);
  }

  private async reload(): Promise<void> {
    this.items.set(await this.request<CaseItem[]>(`/cases?limit=20&offset=${this.offset}`));
  }

  async refresh(delta = 0): Promise<void> {
    await this.run(async () => { this.offset = Math.max(0, this.offset + delta); await this.reload(); });
  }

  async select(id: string): Promise<void> {
    await this.run(async () => {
      this.selected.set(await this.request<CaseDetail>(`/cases/${id}`));
      this.rationale = ''; this.outcome = 'INCONCLUSIVO';
    });
  }

  async analyze(): Promise<void> {
    const item = this.selected(); if (!item) return;
    await this.run(async () => {
      await this.request(`/cases/${item.id}/reports`, { expected_version: item.version });
      this.selected.set(await this.request<CaseDetail>(`/cases/${item.id}`));
      await this.reload();
    });
  }

  async review(): Promise<void> {
    const item = this.selected(); if (!item?.reports.length) return;
    await this.run(async () => {
      await this.request(`/cases/${item.id}/reviews`, {
        report_id: item.reports[0].id, expected_version: item.version, outcome: this.outcome, rationale: this.rationale
      });
      this.selected.set(await this.request<CaseDetail>(`/cases/${item.id}`));
      await this.reload(); this.rationale = '';
    });
  }

  can(scope: string): boolean { return !!this.identity()?.scopes.includes(scope); }
}
