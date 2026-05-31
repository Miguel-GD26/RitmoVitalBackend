"""
classifier.services.pdf_service — Generación de reportes PDF para análisis ECG.

Encapsula todo el layout matplotlib/PdfPages, manteniéndolo separado
de la view que lo invoca (AnalysisPdfView).
"""

import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
from django.http import HttpResponse
from django.utils import timezone


_DARK_BLUE    = '#174a7a'
_ACCENT_BLUE  = '#1e88e5'
_SUCCESS      = '#16a34a'
_DANGER       = '#dc2626'
_SUPRA_COLOR  = '#2563eb'
_FUSION_COLOR = '#d97706'
_LIGHT_BG     = '#f8fafc'
_TEXT_MAIN    = '#1a202c'
_TEXT_MUTED   = '#718096'
_BORDER       = '#e2e8f0'

_CLASS_COLORS = {
    'Normal (N)':           _SUCCESS,
    'Supraventricular (S)': _SUPRA_COLOR,
    'Ventricular (V)':      _DANGER,
    'Fusión (F)':           _FUSION_COLOR,
}


def _add_rect(fig, x, y, w, h, fc, ec='none', lw=1.0, zorder=1):
    rect = mpatches.Rectangle(
        (x, y), w, h,
        transform=fig.transFigure,
        fill=True, facecolor=fc, edgecolor=ec,
        linewidth=lw, zorder=zorder,
    )
    fig.add_artist(rect)


def generate_analysis_pdf(analisis) -> HttpResponse:
    """Reporte PDF A4 para un AnalisisECG. Requiere select_related('paciente', 'usuario')."""
    buffer = io.BytesIO()
    with PdfPages(buffer) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait
        fig.patch.set_facecolor('white')

        # ── 1. Header band ─────────────────────────────────────────
        _add_rect(fig, 0, 0.913, 1, 0.087, fc=_DARK_BLUE, zorder=1)

        fig.text(0.055, 0.975, 'RitmoVital',
                 fontsize=19, fontweight='bold', color='white',
                 transform=fig.transFigure, zorder=2, va='center')
        fig.text(0.055, 0.942, 'Reporte de Análisis ECG',
                 fontsize=10, color='#9ec5e8',
                 transform=fig.transFigure, zorder=2, va='center')

        fig.text(0.945, 0.975, f'Análisis #{analisis.id}',
                 fontsize=13, fontweight='bold', color='white',
                 transform=fig.transFigure, ha='right', zorder=2, va='center')
        fig.text(0.945, 0.942,
                 analisis.fecha.strftime('%d de %B de %Y'),
                 fontsize=8.5, color='#9ec5e8',
                 transform=fig.transFigure, ha='right', zorder=2, va='center')

        _add_rect(fig, 0, 0.910, 1, 0.003, fc=_ACCENT_BLUE, zorder=2)

        # ── 2. Patient box (left) ───────────────────────────────────
        _add_rect(fig, 0.04, 0.765, 0.435, 0.130,
                  fc='#EFF6FF', ec='#BFDBFE', lw=1.2, zorder=2)

        fig.text(0.058, 0.884, 'PACIENTE',
                 fontsize=7, fontweight='bold', color='#2563EB',
                 transform=fig.transFigure, zorder=3, va='center')

        if analisis.paciente:
            nombre = f"{analisis.paciente.nombre} {analisis.paciente.apellido}"
            fig.text(0.058, 0.860, nombre,
                     fontsize=11, fontweight='bold', color='#1a365d',
                     transform=fig.transFigure, zorder=3, va='center')
            meta = []
            if analisis.paciente.historia_clinica:
                meta.append(f"HC: {analisis.paciente.historia_clinica}")
            if analisis.paciente.fecha_nacimiento:
                meta.append(f"F. Nac.: {analisis.paciente.fecha_nacimiento:%d/%m/%Y}")
            if analisis.paciente.sexo:
                sexo_map = {'M': 'Masculino', 'F': 'Femenino', 'O': 'Otro'}
                meta.append(sexo_map.get(analisis.paciente.sexo, ''))
            if meta:
                fig.text(0.058, 0.835, '   ·   '.join(meta),
                         fontsize=8.5, color='#4a5568',
                         transform=fig.transFigure, zorder=3, va='center')
            if analisis.paciente.notas:
                notas_short = analisis.paciente.notas[:60] + (
                    '…' if len(analisis.paciente.notas) > 60 else ''
                )
                fig.text(0.058, 0.810, f'Notas: {notas_short}',
                         fontsize=7.5, color=_TEXT_MUTED,
                         transform=fig.transFigure, zorder=3, va='center')
        else:
            fig.text(0.257, 0.834, '—  Sin paciente vinculado  —',
                     fontsize=10, color=_TEXT_MUTED, style='italic',
                     transform=fig.transFigure, ha='center', zorder=3, va='center')

        # ── 3. Analysis box (right) ─────────────────────────────────
        _add_rect(fig, 0.525, 0.765, 0.435, 0.130,
                  fc=_LIGHT_BG, ec=_BORDER, lw=1.2, zorder=2)

        fig.text(0.543, 0.884, 'RESUMEN DEL ANÁLISIS',
                 fontsize=7, fontweight='bold', color='#64748B',
                 transform=fig.transFigure, zorder=3, va='center')

        info_rows = [
            ('Registro ECG',    analisis.record_name or '—'),
            ('Modo',            analisis.get_modo_display()),
            ('Latidos analiz.', f"{analisis.latidos_procesados:,} de {analisis.total_latidos:,}"),
            ('Accuracy',        f"{analisis.accuracy:.2f}%" if analisis.accuracy is not None else 'N/A (producción)'),
            ('Versión modelo',  analisis.modelo_version),
        ]
        y_row = 0.862
        for label, value in info_rows:
            fig.text(0.543, y_row, f'{label}:',
                     fontsize=8, color=_TEXT_MUTED,
                     transform=fig.transFigure, zorder=3, va='center')
            val_color = _SUCCESS if label == 'Accuracy' and analisis.accuracy else _TEXT_MAIN
            fig.text(0.690, y_row, value,
                     fontsize=8, fontweight='600', color=val_color,
                     transform=fig.transFigure, zorder=3, va='center')
            y_row -= 0.022

        # ── 4. ECG signal section ───────────────────────────────────
        fig.text(0.04, 0.752, 'Señal ECG Analizada',
                 fontsize=9, fontweight='bold', color=_DARK_BLUE,
                 transform=fig.transFigure, zorder=2, va='center')
        _add_rect(fig, 0.04, 0.748, 0.92, 0.0015, fc=_BORDER, zorder=2)

        ax_ecg = fig.add_axes([0.04, 0.490, 0.92, 0.252])
        ax_ecg.set_facecolor('#F1F6FC')
        for spine in ax_ecg.spines.values():
            spine.set_color(_BORDER)
        ax_ecg.set_xticks([])
        ax_ecg.set_yticks([])

        ecg_drawn = False
        if analisis.ecg_plot_url:
            try:
                import requests
                from PIL import Image as PilImage
                resp = requests.get(analisis.ecg_plot_url, timeout=10)
                resp.raise_for_status()
                pil_img = PilImage.open(io.BytesIO(resp.content))
                ax_ecg.imshow(pil_img, aspect='auto', interpolation='bilinear')
                ecg_drawn = True
            except Exception:
                pass

        if not ecg_drawn:
            ax_ecg.text(0.5, 0.5,
                        'Gráfico ECG no disponible para este análisis',
                        ha='center', va='center', fontsize=10,
                        color=_TEXT_MUTED, transform=ax_ecg.transAxes)

        # ── 5. Distribution section ─────────────────────────────────
        fig.text(0.04, 0.478, 'Distribución de Clases AAMI EC57:2012',
                 fontsize=9, fontweight='bold', color=_DARK_BLUE,
                 transform=fig.transFigure, zorder=2, va='center')
        _add_rect(fig, 0.04, 0.474, 0.92, 0.0015, fc=_BORDER, zorder=2)

        ax_dist = fig.add_axes([0.04, 0.155, 0.92, 0.310])
        ax_dist.set_facecolor('white')
        ax_dist.spines['top'].set_visible(False)
        ax_dist.spines['right'].set_visible(False)
        ax_dist.spines['left'].set_visible(False)
        ax_dist.spines['bottom'].set_color(_BORDER)

        distribucion = analisis.distribucion_json or {}
        if distribucion:
            canonical_order = ['Normal (N)', 'Supraventricular (S)', 'Ventricular (V)', 'Fusión (F)']
            clases = [c for c in canonical_order if c in distribucion]
            clases += [c for c in distribucion if c not in canonical_order]
            pcts   = [float(distribucion[c]) for c in clases]
            colors = [_CLASS_COLORS.get(c, '#6b7280') for c in clases]

            bars = ax_dist.barh(
                clases, pcts, color=colors, height=0.50,
                zorder=2, alpha=0.88,
            )
            max_pct = max(pcts) if pcts else 100
            ax_dist.set_xlim(0, max_pct * 1.22 + 1)
            ax_dist.grid(axis='x', alpha=0.25, linestyle='--', color='#CBD5E1', zorder=1)
            ax_dist.set_xlabel('Porcentaje de latidos (%)', fontsize=8, color=_TEXT_MUTED)
            ax_dist.tick_params(axis='x', colors=_TEXT_MUTED, labelsize=8)
            ax_dist.tick_params(axis='y', length=0, pad=6)

            ax_dist.set_yticklabels(clases, fontsize=8.5)
            for tick, color in zip(ax_dist.get_yticklabels(), colors):
                tick.set_color(color)
                tick.set_fontweight('semibold')

            for bar, pct in zip(bars, pcts):
                ax_dist.text(
                    pct + max_pct * 0.01,
                    bar.get_y() + bar.get_height() / 2,
                    f'{pct:.2f}%',
                    va='center', ha='left', fontsize=9,
                    fontweight='bold', color='#374151',
                )
        else:
            ax_dist.text(0.5, 0.5, 'Distribución no disponible',
                         ha='center', va='center', fontsize=10,
                         color=_TEXT_MUTED, transform=ax_dist.transAxes)
            ax_dist.axis('off')

        # ── 6. Footer ────────────────────────────────────────────────
        _add_rect(fig, 0.04, 0.095, 0.92, 0.0015, fc=_BORDER, zorder=2)

        medico = analisis.usuario.username if analisis.usuario else '—'
        fig.text(
            0.5, 0.073,
            f'Generado el {timezone.now().strftime("%d/%m/%Y %H:%M")} UTC  '
            f'·  Modelo: {analisis.modelo_version}  ·  Médico: {medico}',
            ha='center', va='center', fontsize=7.5, color=_TEXT_MUTED,
            transform=fig.transFigure, zorder=2,
        )
        fig.text(
            0.5, 0.050,
            'RitmoVital · Sistema de Clasificación de Arritmias ECG  '
            '·  Estándar AAMI EC57:2012  ·  Dataset MIT-BIH',
            ha='center', va='center', fontsize=7, color='#a0aec0',
            transform=fig.transFigure, zorder=2,
        )
        fig.text(
            0.5, 0.030,
            'Moody GB, Mark RG. The impact of the MIT-BIH Arrhythmia Database. '
            'IEEE Eng in Med and Biol 20(3):45–50, 2001.',
            ha='center', va='center', fontsize=6.5, color='#a0aec0',
            style='italic', transform=fig.transFigure, zorder=2,
        )

        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    buffer.seek(0)
    record_slug = analisis.record_name.replace(' ', '_') if analisis.record_name else 'demo'
    fname = f'reporte_ecg_{record_slug}_{analisis.id}.pdf'
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response
