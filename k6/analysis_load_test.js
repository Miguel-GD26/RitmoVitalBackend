/**
 * k6 Load Test — RitmoVital ECG: análisis concurrentes
 *
 * Ejecutar:
 *   k6 run --env BASE_URL=http://localhost:8000 \
 *          --env TOKEN=<jwt_access_token> \
 *          --env DAT_FILE=./samples/100.dat \
 *          --env HEA_FILE=./samples/100.hea \
 *          --env ATR_FILE=./samples/100.atr \
 *          backend/k6/analysis_load_test.js
 *
 * Instalar k6: https://k6.io/docs/getting-started/installation/
 *
 * Objetivos de rendimiento (thresholds):
 *   - 95% de requests < 30 s  (análisis ECG es CPU-heavy)
 *   - Tasa de errores HTTP < 5%
 *   - Polling status: 95% < 2 s
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

// ── Métricas personalizadas ──────────────────────────────────────────────────
const analysisDuration  = new Trend('ecg_analysis_duration_ms', true);
const pollingDuration   = new Trend('ecg_polling_duration_ms', true);
const analysisErrors    = new Rate('ecg_analysis_error_rate');
const tasksCompleted    = new Counter('ecg_tasks_completed');
const tasksFailed       = new Counter('ecg_tasks_failed');

// ── Configuración de escenarios ──────────────────────────────────────────────
export const options = {
  scenarios: {
    // Escenario 1: carga sostenida (simula uso normal en clínica)
    sustained_load: {
      executor: 'constant-arrival-rate',
      rate: 2,           // 2 análisis por minuto
      timeUnit: '1m',
      duration: '5m',
      preAllocatedVUs: 5,
      maxVUs: 10,
    },
    // Escenario 2: pico de carga (varios médicos a la vez)
    burst_load: {
      executor: 'ramping-vus',
      startTime: '5m',   // empieza después del escenario sostenido
      stages: [
        { duration: '1m', target: 8 },   // rampa a 8 VUs
        { duration: '2m', target: 8 },   // sostener
        { duration: '1m', target: 0 },   // bajar
      ],
    },
  },
  thresholds: {
    // Análisis completo (incluyendo polling)
    'ecg_analysis_duration_ms': ['p(95)<30000'],   // 95% < 30 s
    // Endpoint de status
    'ecg_polling_duration_ms':  ['p(95)<2000'],    // 95% < 2 s
    // Errores HTTP generales
    'http_req_failed':          ['rate<0.05'],     // < 5% errores
    // Tasa de errores ECG
    'ecg_analysis_error_rate':  ['rate<0.05'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const TOKEN    = __ENV.TOKEN    || '';

// ── Helpers ──────────────────────────────────────────────────────────────────

function authHeaders() {
  return {
    'Authorization': `Bearer ${TOKEN}`,
  };
}

/**
 * Carga un archivo del filesystem k6 como bytes.
 * En producción, los archivos ECG deben estar en la carpeta ./samples/.
 */
function loadEcgFiles() {
  // k6 no soporta `open()` con archivos binarios en todos los entornos.
  // Si los archivos no están disponibles, se omite este escenario.
  try {
    const dat = open(__ENV.DAT_FILE || './samples/100.dat', 'b');
    const hea = open(__ENV.HEA_FILE || './samples/100.hea', 'b');
    const atr = open(__ENV.ATR_FILE || './samples/100.atr', 'b');
    return { dat, hea, atr };
  } catch (_) {
    return null;
  }
}

// Carga los archivos una sola vez (init stage, fuera del default function)
const ecgFiles = loadEcgFiles();

// ── Prueba de status endpoint (sin archivos reales) ──────────────────────────

export function testStatusEndpoint() {
  const fakeTaskId = 'aaaabbbbccccdddd1234567890abcdef';
  const start = Date.now();
  const res = http.get(
    `${BASE_URL}/api/v1/analysis/status/${fakeTaskId}/`,
    { headers: authHeaders() }
  );
  pollingDuration.add(Date.now() - start);

  check(res, {
    'status endpoint responde': r => r.status === 200 || r.status === 404,
    'responde en < 1s': r => r.timings.duration < 1000,
  });
}

// ── Flujo completo: submit → poll → resultado ────────────────────────────────

export function testFullAnalysisFlow() {
  if (!ecgFiles) {
    console.warn('Archivos ECG no disponibles — omitiendo análisis completo');
    return;
  }

  const formData = {
    dat_file: http.file(ecgFiles.dat, '100.dat', 'application/octet-stream'),
    hea_file: http.file(ecgFiles.hea, '100.hea', 'application/octet-stream'),
    atr_file: http.file(ecgFiles.atr, '100.atr', 'application/octet-stream'),
    page: '1',
    page_size: '100',
  };

  const submitStart = Date.now();
  const submitRes = http.post(
    `${BASE_URL}/api/v1/analyze-patient/`,
    formData,
    { headers: authHeaders(), timeout: '60s' }
  );

  const submitOk = check(submitRes, {
    'submit status 200': r => r.status === 200,
    'tiene task_id':     r => {
      try { return !!JSON.parse(r.body).data.task_id; } catch { return false; }
    },
  });

  if (!submitOk) {
    analysisErrors.add(1);
    return;
  }

  const taskId = JSON.parse(submitRes.body).data.task_id;

  // Polling hasta completed/failed (máx. 60 intentos × 1 s = 60 s)
  let completed = false;
  for (let i = 0; i < 60; i++) {
    sleep(1);
    const pollStart = Date.now();
    const pollRes = http.get(
      `${BASE_URL}/api/v1/analysis/status/${taskId}/`,
      { headers: authHeaders() }
    );
    pollingDuration.add(Date.now() - pollStart);

    check(pollRes, { 'poll status 200': r => r.status === 200 });

    try {
      const body = JSON.parse(pollRes.body);
      const status = body.data?.status;

      if (status === 'completed') {
        analysisDuration.add(Date.now() - submitStart);
        tasksCompleted.add(1);
        analysisErrors.add(0);
        completed = true;
        break;
      }
      if (status === 'failed') {
        analysisErrors.add(1);
        tasksFailed.add(1);
        completed = true;
        break;
      }
    } catch (_) {
      analysisErrors.add(1);
      break;
    }
  }

  if (!completed) {
    console.error(`Tarea ${taskId} no completó en 60 s`);
    analysisErrors.add(1);
    tasksFailed.add(1);
  }
}

// ── Función principal ────────────────────────────────────────────────────────

export default function () {
  // Distribuir carga: 70% análisis completo, 30% solo status
  if (Math.random() < 0.7) {
    testFullAnalysisFlow();
  } else {
    testStatusEndpoint();
  }
  sleep(Math.random() * 2 + 1); // pausa entre 1 y 3 s
}
