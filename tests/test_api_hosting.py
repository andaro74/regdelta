"""SPEC/04's deployed surface: the HTTP API and the demo distribution.

Both are new at M04 and both are internet-facing, so the properties worth
pinning are the ones whose absence is invisible in a green deploy: a bucket that
is private, an API that refuses paths it does not serve, a throttle on an
endpoint that spends Bedrock tokens per request, and a CloudFront behaviour that
does not become a second uncontrolled answer cache.

The path contract is the fragile one and it spans two services. The stage is
NAMED `api`, so API Gateway answers at `/api/query`; CloudFront forwards
`/api/*` verbatim to it. Rename either half and the demo 404s while every
resource still deploys — which is exactly the class of failure that has no test
until someone writes one.
"""
import contextlib
import pathlib
import sys
import tempfile
from pathlib import Path

import pytest

aws_cdk = pytest.importorskip("aws_cdk", reason="CDK not installed")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "infra"))

# The dependency layer is a BUILD ARTIFACT (`make layer`, ~101MB) and is not
# committed, so the stack refuses to synth without it — deliberately, because
# an empty layer deploys a function whose imports fail in the region. Tests
# assert stack SHAPE, so they stub the path with an empty directory. One test
# below asserts the refusal itself, which is the guard that makes the rest of
# this safe.
@contextlib.contextmanager
def stub_layer():
    from core import core_stack

    original = core_stack.LAYER_SRC
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "python").mkdir()
        core_stack.LAYER_SRC = Path(tmp)
        try:
            yield
        finally:
            core_stack.LAYER_SRC = original



@pytest.fixture(scope="module")
def template():
    import aws_cdk as cdk
    from core.core_stack import RegDeltaCoreStack

    app = cdk.App(outdir=tempfile.mkdtemp())
    with stub_layer():
        RegDeltaCoreStack(app, "regdelta-core", env=cdk.Environment(
            account="111122223333", region="us-west-2"))
    return app.synth().get_stack_by_name("regdelta-core").template


def staged_files(assembly) -> dict:
    """Every asset `cdk synth` staged, as {asset dir name: {relative paths}}.

    Assets are staged as DIRECTORIES and zipped at publish time, so this reads
    what will be uploaded rather than what the template says was asked for. The
    distinction is the point of the two tests below: the template records an
    asset hash, and a hash cannot say whether a `.env` is inside it.
    """
    out = {}
    for asset in sorted(pathlib.Path(assembly.directory).glob("asset.*")):
        if not asset.is_dir():
            continue
        out[asset.name] = {
            f.relative_to(asset).as_posix()
            for f in asset.rglob("*") if f.is_file()
        }
    return out


def resources(template, kind):
    return [r["Properties"] for r in template["Resources"].values()
            if r["Type"] == kind]


def one(template, kind):
    found = resources(template, kind)
    assert len(found) == 1, f"expected exactly one {kind}, got {len(found)}"
    return found[0]


# ------------------------------------------------------------------ the API
def test_only_the_three_routes_spec_04_defines_are_reachable():
    """`ANY /{proxy+}` would hand the Lambda every path an attacker tries and
    rely on FastAPI to refuse them. Three routes mean API Gateway refuses
    everything else before a request reaches code that costs money."""
    import aws_cdk as cdk
    from core.core_stack import RegDeltaCoreStack

    app = cdk.App(outdir=tempfile.mkdtemp())
    with stub_layer():
        RegDeltaCoreStack(app, "regdelta-core", env=cdk.Environment(
            account="111122223333", region="us-west-2"))
    t = app.synth().get_stack_by_name("regdelta-core").template
    routes = sorted(r["RouteKey"] for r in resources(t, "AWS::ApiGatewayV2::Route"))
    assert routes == ["GET /health", "POST /query", "POST /resume/{thread_id}"]
    assert not any("proxy" in r or r.startswith("ANY") for r in routes)


def test_the_stage_is_named_api_because_cloudfront_forwards_that_prefix(template):
    """Half of a contract spanning two services. The stage name is the first
    path segment, so `api` is what makes /api/query resolve with no rewriting
    at either end."""
    assert one(template, "AWS::ApiGatewayV2::Stage")["StageName"] == "api"


def test_the_unauthenticated_endpoint_is_throttled(template):
    """/query is unauthenticated by SPEC/04's own scope decision and spends a
    Bedrock call per request. Without a ceiling the only limit on a stranger's
    bill is Lambda account concurrency."""
    settings = one(template, "AWS::ApiGatewayV2::Stage")["DefaultRouteSettings"]
    assert settings["ThrottlingRateLimit"] > 0
    assert settings["ThrottlingBurstLimit"] > 0


def test_tooling_depends_on_these_output_names(template):
    """`run_evals.resolve_api_url` reads ApiUrl and the Makefile's `demo` target
    reads DemoUrl. Renaming either breaks a command rather than a build."""
    assert {"ApiUrl", "DemoUrl"} <= set(template["Outputs"])


# ------------------------------------------------------------- the UI bucket
def test_the_ui_bucket_is_private(template):
    """It is reachable only through CloudFront's origin access control. A demo
    bucket made public is the oldest S3 mistake there is."""
    buckets = resources(template, "AWS::S3::Bucket")
    ui = [b for b in buckets
          if b.get("PublicAccessBlockConfiguration") and "WebsiteConfiguration" not in b]
    assert ui, "no bucket with public access blocked"
    for b in buckets:
        block = b.get("PublicAccessBlockConfiguration")
        assert block == {"BlockPublicAcls": True, "BlockPublicPolicy": True,
                         "IgnorePublicAcls": True, "RestrictPublicBuckets": True}, b
        assert "WebsiteConfiguration" not in b, \
            "a website-configured bucket serves over plain HTTP, bypassing CloudFront"


def test_no_bucket_policy_grants_a_wildcard_principal(template):
    """OAC grants CloudFront specifically. `Principal: "*"` would serve the
    bucket to the internet directly, around every control on the distribution."""
    for policy in resources(template, "AWS::S3::BucketPolicy"):
        for stmt in policy["PolicyDocument"]["Statement"]:
            if stmt.get("Effect") != "Allow":
                continue
            assert stmt.get("Principal") != "*", stmt
            assert stmt.get("Principal", {}) != {"AWS": "*"}, stmt


# ------------------------------------------------------------- the front door
def test_every_behaviour_forces_https(template):
    dist = one(template, "AWS::CloudFront::Distribution")["DistributionConfig"]
    behaviours = [dist["DefaultCacheBehavior"], *dist.get("CacheBehaviors", [])]
    for b in behaviours:
        assert b["ViewerProtocolPolicy"] == "redirect-to-https", b


def test_the_api_behaviour_does_not_cache_answers(template):
    """A CloudFront cache in front of /query would be a second answer cache with
    no stated TTL and no bypass — and SPEC/04's control 1, which requires both
    `make demo-parity` tier runs to bypass the cache, would be measuring it."""
    dist = one(template, "AWS::CloudFront::Distribution")["DistributionConfig"]
    api_behaviour = next(b for b in dist["CacheBehaviors"]
                         if b["PathPattern"] == "/api/*")
    # CachePolicyId is the managed CACHING_DISABLED policy's fixed id.
    assert api_behaviour["CachePolicyId"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"


def test_the_api_behaviour_forwards_the_headers_the_api_needs(template):
    """`x-regdelta-no-cache` is how a caller bypasses the response cache. A
    behaviour that forwarded only a header allowlist would silently drop it, and
    the demo's bypass control would do nothing while appearing to work."""
    dist = one(template, "AWS::CloudFront::Distribution")["DistributionConfig"]
    api_behaviour = next(b for b in dist["CacheBehaviors"]
                         if b["PathPattern"] == "/api/*")
    # ALL_VIEWER_EXCEPT_HOST_HEADER — everything but Host, which API Gateway
    # must see as its own to route.
    assert api_behaviour["OriginRequestPolicyId"] == \
        "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    assert api_behaviour["AllowedMethods"] == ["GET", "HEAD", "OPTIONS", "PUT",
                                               "PATCH", "POST", "DELETE"]


def test_the_api_behaviour_points_at_the_api_not_the_bucket(template):
    """Both origins live on one distribution; crossing them serves the UI's
    index.html in answer to a POST /api/query."""
    dist = one(template, "AWS::CloudFront::Distribution")["DistributionConfig"]
    origins = {o["Id"]: o for o in dist["Origins"]}
    api_behaviour = next(b for b in dist["CacheBehaviors"]
                         if b["PathPattern"] == "/api/*")
    api_origin = origins[api_behaviour["TargetOriginId"]]
    assert "CustomOriginConfig" in api_origin, "the /api/* origin must be the HTTP API"
    domain = str(api_origin["DomainName"])
    assert "execute-api" in domain, domain

    default_origin = origins[dist["DefaultCacheBehavior"]["TargetOriginId"]]
    assert "S3OriginConfig" in default_origin or \
        "OriginAccessControlId" in default_origin, default_origin


def test_the_distribution_serves_index_html_at_the_root(template):
    dist = one(template, "AWS::CloudFront::Distribution")["DistributionConfig"]
    assert dist["DefaultRootObject"] == "index.html"


def test_the_stage_name_and_the_lambda_base_path_cannot_drift(template):
    """A contract across two files: the stage name is the path prefix API
    Gateway adds, and API_BASE_PATH is what Mangum strips before FastAPI
    routes. If they disagree, every route 404s with FastAPI's own body — which
    reads like an application bug and is a packaging one. It shipped that way.
    """
    stage = one(template, "AWS::ApiGatewayV2::Stage")["StageName"]
    query_fn = next(r["Properties"] for r in template["Resources"].values()
                    if r["Type"] == "AWS::Lambda::Function"
                    and r["Properties"].get("Handler") == "api.api.handler")
    assert query_fn["Environment"]["Variables"]["API_BASE_PATH"] == f"/{stage}"


# ---------------------------------------------------- what reaches the bucket
def test_only_the_two_files_the_page_is_reach_the_public_bucket(tmp_path):
    """The UI bucket is served by CloudFront to anyone, with no IAM in the way.

    Measured through the stack's OWN constants against a planted tree, not
    asserted over the real `ui/` — a clean checkout has nothing to leak, so a
    test written that way passes vacuously, which is precisely the defect
    `security-reviewer` found in the first version of the Lambda-asset test this
    one is modelled on.

    Reproduced before it was fixed: `Source.asset(UI_SRC)` carried no filter and
    staged `['.env', '__pycache__/x.pyc', 'index.html', 'notes.md',
    'verdict.js']`.
    """
    import asset_policy
    import aws_cdk as cdk
    from aws_cdk import aws_s3_deployment as s3deploy

    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (ui / "verdict.js").write_text("// judgement", encoding="utf-8")
    # Everything below is a plausible accident, and each would be readable by
    # anyone with the distribution URL.
    (ui / ".env").write_text("AWS_SECRET_ACCESS_KEY=hunter2", encoding="utf-8")
    (ui / "index.old.html").write_text("<!-- last week's page -->", encoding="utf-8")
    (ui / "notes.md").write_text("internal", encoding="utf-8")
    (ui / "verdict.js.bak").write_text("// judgement, previously", encoding="utf-8")
    (ui / "__pycache__").mkdir()
    (ui / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (ui / ".git").mkdir()
    (ui / ".git" / "config").write_text("[remote]", encoding="utf-8")

    app = cdk.App(outdir=str(tmp_path / "out"))
    stack = cdk.Stack(app, "probe")
    bucket = __import__("aws_cdk").aws_s3.Bucket(stack, "B")
    s3deploy.BucketDeployment(
        stack, "D",
        sources=[s3deploy.Source.asset(str(ui),
                                       exclude=asset_policy.UI_ASSET_EXCLUDE,
                                       ignore_mode=asset_policy.ASSET_IGNORE_MODE)],
        destination_bucket=bucket)
    # BucketDeployment stages its own handler lambda as a second asset; the
    # one under test is whichever carries a file the page is made of.
    ours = [names for names in staged_files(app.synth()).values()
            if names & {"index.html", "verdict.js", "notes.md", ".env"}]
    assert len(ours) == 1, ours
    assert ours[0] == {"index.html", "verdict.js"}, sorted(ours[0])


def test_the_stack_applies_that_allowlist_to_the_ui_bucket(tmp_path):
    """The constants above are only worth testing if THE STACK uses them.

    Synthesised against a PLANTED `ui/`, by redirecting the stack's own
    `UI_SRC` — the way `stub_layer` redirects `LAYER_SRC`. The first version of
    this test synthesised over the real `ui/`, which holds two files and has
    nothing to leak, so it passed with the allowlist deleted from the stack
    entirely: green by construction, one level down, in the test written to
    close a leak. That is the same defect `security-reviewer` found in the first
    version of the Lambda-asset test this one is modelled on, and it was caught
    the same way — by re-introducing the bug and checking the test noticed.

    Two assets reach the UI bucket, the allowlisted tree and the generated
    `scenarios.json`, so this asserts their union.
    """
    import aws_cdk as cdk
    from core import core_stack

    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (ui / "verdict.js").write_text("// judgement", encoding="utf-8")
    (ui / ".env").write_text("AWS_SECRET_ACCESS_KEY=hunter2", encoding="utf-8")
    (ui / "index.old.html").write_text("<!-- last week -->", encoding="utf-8")
    (ui / "notes.md").write_text("internal", encoding="utf-8")

    app = cdk.App(outdir=str(tmp_path / "out"))
    original = core_stack.UI_SRC
    core_stack.UI_SRC = str(ui)
    try:
        with stub_layer():
            core_stack.RegDeltaCoreStack(
                app, "regdelta-core",
                env=cdk.Environment(account="111122223333", region="us-west-2"))
        assembly = app.synth()
    finally:
        core_stack.UI_SRC = original

    # The Lambda code assets ship the `src/` tree and are asserted elsewhere;
    # the UI's are the ones carrying a file the page is made of.
    published = set()
    for names in staged_files(assembly).values():
        if names & {"index.html", "verdict.js", "scenarios.json",
                    "notes.md", ".env", "index.old.html"}:
            published |= names
    assert published == {"index.html", "verdict.js", "scenarios.json"}, sorted(published)
