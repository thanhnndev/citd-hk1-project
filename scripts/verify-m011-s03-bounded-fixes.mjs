import { access, readFile } from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const repoRoot = path.resolve(import.meta.dirname, '..');

const files = {
  audit: 'docs/M011-REQUIREMENTS-AUDIT.md',
  adminRouter: 'backend/app/routers/admin.py',
  adminEvalTests: 'backend/tests/test_admin_eval_endpoint.py',
  adminStatsTests: 'backend/tests/test_admin_stats_endpoint.py',
  adminTracesTests: 'backend/tests/test_admin_traces_endpoint.py',
  adminEmbedTests: 'backend/tests/test_admin_embed_auth.py',
  adminApiClient: 'frontend/src/lib/admin-api.ts',
  adminProxy: 'frontend/src/app/api/admin/route.ts',
  fairnessScript: 'scripts/monthly_fairness_audit.py',
  fairnessTests: 'backend/tests/test_fairness_audit.py',
  frontendPackage: 'frontend/package.json',
  backendRequirements: 'backend/requirements.txt',
  agentsRequirements: 'agents/requirements.txt',
};

function repoPath(relativePath) {
  return path.join(repoRoot, relativePath);
}

async function read(relativePath) {
  const absolutePath = repoPath(relativePath);
  await access(absolutePath, constants.R_OK);
  return readFile(absolutePath, 'utf8');
}

function normalizeText(value) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[đĐ]/g, 'd')
    .replace(/[^\p{L}\p{N}/_.:-]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .trim();
}

function assertContainsAll(haystack, needles, context) {
  const normalizedHaystack = normalizeText(haystack);
  for (const needle of needles) {
    assert.ok(
      normalizedHaystack.includes(normalizeText(needle)),
      `${context} is missing required token: ${needle}`,
    );
  }
}

function assertRouteHasAuth(source, decorator, functionName) {
  const decoratorIndex = source.indexOf(decorator);
  assert.notEqual(decoratorIndex, -1, `Admin router is missing ${decorator}.`);

  const nextDecoratorIndex = source.indexOf('\n@router.', decoratorIndex + decorator.length);
  const routeBlock = source.slice(
    decoratorIndex,
    nextDecoratorIndex === -1 ? source.length : nextDecoratorIndex,
  );

  assert.match(
    routeBlock,
    new RegExp(`async def\\s+${functionName}\\s*\\(`),
    `${decorator} is not attached to ${functionName}.`,
  );
  assert.match(
    routeBlock,
    /current_user\s*=\s*Depends\(get_current_user\)/,
    `${decorator} / ${functionName} is not protected by get_current_user.`,
  );
}

test('M011/S03 audit report preserves bounded remediation candidates and caveat vocabulary', async () => {
  const audit = await read(files.audit);

  assert.match(
    audit,
    /^##\s+S03 Candidates\s*$/m,
    'Audit report is missing the S03 bounded remediation candidate section.',
  );
  assertContainsAll(
    audit,
    [
      'Bounded fix',
      'Bounded verification',
      'Explicit deferral',
      'S03 Remediation Outcomes',
      'fixed+deferred',
      'credential_blocked',
      'endpoint_naming_drift',
      'version_drift',
      'missing_operational_metrics',
      'prior_evidence_may_drift',
      'RAGAS/semantic cache scope decision',
    ],
    'M011 audit report',
  );

  assertContainsAll(
    audit,
    [
      'Reconcile admin endpoint naming',
      'Add/administer route table verifier',
      'Record frontend non-functional proof',
      'Strengthen fairness audit evidence',
      'Preserve credential-blocked provider gates',
      'Update version contract',
      'scripts/verify-m011-s03-bounded-fixes.mjs',
      'POST /admin/eval/trigger',
      'NO_DATA is an honest local result',
      'No Redis semantic-cache production behavior or RAGAS CI/CD is implemented',
    ],
    'M011 S03 remediation outcome log',
  );
});

test('M011/S03 backend admin route contract uses current /admin/eval/trigger naming and auth', async () => {
  const adminRouter = await read(files.adminRouter);

  assert.match(adminRouter, /router\s*=\s*APIRouter\(prefix=["']\/admin["']/, 'Admin router prefix must remain /admin.');
  assertRouteHasAuth(adminRouter, '@router.post("/embed"', 'embed_corpus');
  assertRouteHasAuth(adminRouter, '@router.post(\n    "/eval/trigger"', 'trigger_eval');
  assertRouteHasAuth(adminRouter, '@router.get("/eval/results"', 'list_eval_results');
  assertRouteHasAuth(adminRouter, '@router.get("/traces"', 'get_traces');
  assertRouteHasAuth(adminRouter, '@router.get("/fairness"', 'get_fairness');
  assertRouteHasAuth(adminRouter, '@router.get("/stats"', 'get_stats');

  assert.doesNotMatch(
    adminRouter,
    /@router\.post\(["']\/eval["']/,
    'Do not reintroduce stale POST /admin/eval; current contract is POST /admin/eval/trigger.',
  );
});

test('M011/S03 frontend admin client and proxy preserve /api/admin plus /eval/trigger contract', async () => {
  const [client, proxy] = await Promise.all([
    read(files.adminApiClient),
    read(files.adminProxy),
  ]);

  assertContainsAll(client, ['/api/admin', '/eval/trigger', '/eval/results', '/traces', '/fairness', '/stats'], 'frontend admin API client');
  assert.match(proxy, /replace\(\/\^\\\/api\\\/admin\/,\s*["']\/admin["']\)/, 'Frontend proxy must translate /api/admin/* to /admin/*.');
  assert.match(proxy, /Authorization/i, 'Frontend proxy must preserve Authorization headers for admin routes.');
});

test('M011/S03 admin auth tests cover eval, traces, fairness, stats, and embed protected routes', async () => {
  const testSources = Object.fromEntries(await Promise.all([
    files.adminEvalTests,
    files.adminStatsTests,
    files.adminTracesTests,
    files.adminEmbedTests,
  ].map(async (relativePath) => [relativePath, await read(relativePath)])));
  const combined = Object.values(testSources).join('\n');

  for (const route of ['/admin/eval/trigger', '/admin/eval/results', '/admin/traces', '/admin/fairness', '/admin/stats', '/admin/embed']) {
    assert.ok(combined.includes(route), `Admin test suite is missing protected route coverage for ${route}.`);
  }

  for (const source of Object.values(testSources)) {
    assertContainsAll(source, ['no_auth', '401', 'decode_access_token'], 'admin auth test source');
  }
});

test('M011/S03 fairness audit evidence stays bounded to local JSONL aggregation and script PASS/FAIL/NO_DATA behavior', async () => {
  const [script, tests] = await Promise.all([
    read(files.fairnessScript),
    read(files.fairnessTests),
  ]);

  assertContainsAll(script, ['data/fairness_audit', '*.jsonl', 'PASS', 'FAIL', 'NO_DATA', 'analyze_local_factors'], 'monthly fairness audit script');
  assertContainsAll(tests, ['fairness_audit', 'local_factors', 'total_audits', 'local_factor_distribution', '/admin/fairness'], 'fairness audit tests');
  assert.doesNotMatch(
    script,
    new RegExp(['openai', 'go' + 'ong', 'qdrant', 'langfuse'].join('|'), 'i'),
    'Fairness audit script must remain a local JSONL aggregation diagnostic, not live provider proof.',
  );
});

test('M011/S03 version and provider drift remain documented as static or credential-blocked evidence', async () => {
  const [audit, frontendPackage, backendRequirements, agentsRequirements] = await Promise.all([
    read(files.audit),
    read(files.frontendPackage),
    read(files.backendRequirements),
    read(files.agentsRequirements),
  ]);

  assertContainsAll(audit, ['version_drift', 'credential_blocked', 'Static traceability proof only', 'does not prove live OpenAI, Goong, Qdrant, Postgres/Redis, or Langfuse behavior'], 'M011 audit drift documentation');
  assertContainsAll(frontendPackage, ['next', 'react', 'typescript'], 'frontend package manifest');
  assertContainsAll(backendRequirements, ['openai==', 'qdrant-client==', 'ragas=='], 'backend requirements');
  assertContainsAll(agentsRequirements, ['qdrant-client==', 'ragas==', 'langfuse=='], 'agents requirements');
});
