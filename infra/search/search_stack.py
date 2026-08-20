"""regdelta-search — the EPHEMERAL stack. Everything here is cattle.

AOSS VECTORSEARCH collection in dev mode (standby_replicas=DISABLED →
0.5 + 0.5 OCU ≈ $0.24/hr), three mandatory policies, a reindex Lambda that
hydrates from the corpus bucket on every deploy, and the SSM endpoint param
that flips the retrieval router to the hot tier.

`cdk destroy regdelta-search` must always succeed and loses nothing: the
index is a pure function of the corpus bucket. StandbyReplicas cannot be
changed after index creation — fine, the stack is disposable. Production =
ENABLED + VPC network policy + never destroyed.
"""
import json
import os
import re

import asset_policy
import aws_cdk as cdk
from aws_cdk import (
    Duration,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_opensearchserverless as aoss,
    aws_s3 as s3,
    aws_ssm as ssm,
    triggers,
)
from constructs import Construct

# WHAT THE REINDEX LAMBDA IS ALLOWED TO SHIP. The policy itself now lives in
# infra/asset_policy.py, because the core stack packages the same tree and had
# no filter at all — two copies of a packaging rule is the shape that drifted
# _EDGE_PREDICATE at M01c. Re-exported here so callers and tests can keep
# reading the policy off the stack that applies it.
#
# Everything below is the reasoning, kept where the reader of this stack meets
# it; asset_policy.py carries the same argument for the same reason.
#
# IGNORE MODE IS LOAD-BEARING, and the default is wrong for an allowlist.
# Measured at M04, not reasoned about: the deploy failed with "No module named
# 'retrieval'" and the staged asset held two files — src/__init__.py and
# .pytest_cache/.gitignore.
#
# Under the default (IgnoreMode.GLOB) these patterns go through minimatch,
# where `*` matches every top-level ENTRY including directories, and a pruned
# directory can never be re-entered by a later negation — so `!**/*.py` reached
# nothing below the root. And minimatch's `*` does not match a dot-prefixed
# name, so a ROOT-LEVEL `.env` was staged. (Only root level: the same pruning
# that dropped the source tree also kept the walker out of `.aws/`. The first
# version of this comment said `.aws/credentials` and `.git/` leaked too, which
# the security review measured and refuted — an allowlist's rationale is a
# security claim and has to be exactly as true as it says it is.)
#
# DOCKER is .dockerignore semantics: every path is tested on its own, so a
# negation re-includes files under an excluded directory, and `*` matches
# dotfiles. Verified against a tree containing .env, .aws/credentials, dev.env,
# secrets.json, a `credentials` file with no extension and __pycache__: only
# **/*.py ships, at every depth. GIT mode prunes directories the way GLOB does.
#
# The third pattern closes the one hole the review found in the second: `*`
# excludes a DIRECTORY named `keys.py`, `!**/*.py` then matches that directory
# and re-includes its whole subtree, so `keys.py/secret.txt` shipped. Last
# match wins, so re-excluding anything BELOW a `.py` path component costs one
# pattern and cannot affect a real module, which has nothing below it.
#
# Symlinks are not a hole here: follow_symlinks defaults to
# SymlinkFollowMode.NEVER, so a link is copied as a link and never dereferenced.
ASSET_EXCLUDE = asset_policy.ASSET_EXCLUDE
ASSET_IGNORE_MODE = asset_policy.ASSET_IGNORE_MODE

COLLECTION_NAME = "regdelta"
SSM_ENDPOINT_PARAM = "/regdelta/search/endpoint"

# An AOSS data-access policy principal must be an IAM user or role ARN. The
# assumed-role form `aws sts get-caller-identity` returns is deliberately NOT
# accepted — AOSS does not match on it, and the failure mode is a bare 403 that
# reads like policy propagation.
_DEV_PRINCIPAL_RE = re.compile(
    r"arn:aws[a-z-]*:iam::(?P<account>\d{12}):(?:user|role)/[\w+=,.@/-]+")


class RegDeltaSearchStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *,
                 corpus_bucket: s3.IBucket, query_lambda_role_arn: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        enc = aoss.CfnSecurityPolicy(
            self, "EncryptionPolicy",
            name=f"{COLLECTION_NAME}-enc", type="encryption",
            policy=json.dumps({
                "Rules": [{"ResourceType": "collection",
                           "Resource": [f"collection/{COLLECTION_NAME}"]}],
                "AWSOwnedKey": True,  # enterprise swap: customer-managed KMS
            }))

        net = aoss.CfnSecurityPolicy(
            self, "NetworkPolicy",
            name=f"{COLLECTION_NAME}-net", type="network",
            policy=json.dumps([{
                "Rules": [
                    {"ResourceType": "collection",
                     "Resource": [f"collection/{COLLECTION_NAME}"]},
                    {"ResourceType": "dashboard",
                     "Resource": [f"collection/{COLLECTION_NAME}"]},
                ],
                "AllowFromPublic": True,  # enterprise swap: VPC endpoint
            }]))

        collection = aoss.CfnCollection(
            self, "Collection",
            name=COLLECTION_NAME, type="VECTORSEARCH",
            standby_replicas="DISABLED",
            description="RegDelta hot tier (BM25+kNN). Ephemeral; rebuilt "
                        "from the corpus bucket on every deploy.")
        collection.add_dependency(enc)
        collection.add_dependency(net)

        # Ships ../src, like every core Lambda. It used to ship its own
        # lambdas/reindex/ directory holding a second copy of the index
        # mapping — the same shape as the _EDGE_PREDICATE duplication that
        # drifted in M01c. The mapping and the query tier must agree on field
        # names or cross-tier Jaccard measures the disagreement instead of the
        # retrieval; one importable module makes that unrepresentable.
        # SPEC/02's Files list is amended in the same PR.

        # SPEC/02 Done-when (B) needs a REAL failed deploy, and reindex.py's
        # FAULT_DROP hook reads REINDEX_FAULT_DROP from the Lambda environment —
        # which nothing was passing, so the hook was unit-tested and unreachable
        # in production. Same context idiom as devPrincipalArn below, and
        # deliberately absent from the environment unless asked for:
        # `cdk deploy regdelta-search -c faultDrop=3`.
        #
        # One-directional by construction. The hook can only DROP records before
        # indexing, after which reindex.py's own count assertion fails — there is
        # no switch anywhere that relaxes that assertion (tests/
        # test_reindex_parity.py asserts the property by reading the source). So
        # this can only ever cause a failing deploy, never convert a partial
        # index into a reported success.
        reindex_env = {
            "CORPUS_BUCKET": corpus_bucket.bucket_name,
            "COLLECTION_ENDPOINT": collection.attr_collection_endpoint,
        }
        fault_drop = self.node.try_get_context("faultDrop")
        if fault_drop is not None:
            # int() rejects non-numeric loudly at synth. Sign and zero need
            # rejecting too: `-c faultDrop=0` or `=-3` produces a normal,
            # PASSING deploy while the operator believes the fault fired, which
            # is the wrong direction for evidence-gathering — (B) needs a deploy
            # that failed, and silence about why it didn't is worse than an
            # error.
            drop = int(fault_drop)
            if drop < 1:
                raise ValueError(
                    f"faultDrop must be >= 1, got {drop}. It exists to FAIL a "
                    "deploy for SPEC/02 Done-when (B); a value below 1 drops "
                    "nothing and deploys normally, which looks like the fault "
                    "hook not working.")
            reindex_env["REINDEX_FAULT_DROP"] = str(drop)

        reindex = _lambda.Function(
            self, "ReindexFn",
            runtime=_lambda.Runtime.PYTHON_3_14,
            handler="retrieval.reindex.handler",
            # The asset root is the whole of src/ (see the note above on why the
            # index mapping is not duplicated into infra/lambdas/). This is an
            # ALLOWLIST, not a denylist, and that distinction is the whole point:
            # the guard is meant to hold against anything later dropped into src/
            # — a scratch .env, a downloaded credential — and a denylist only
            # holds against the shapes someone thought to name. The previous list
            # missed `dev.env` (it matched `**/.env.*`, not `**/*.env`),
            # `credentials`, `*.p12`, `*.pfx`, `*.crt` and any JSON key file.
            # Security review of this branch, finding L4.
            #
            # The reindex Lambda needs nothing but Python source: verified that
            # src/ contains no non-.py runtime file. Adding a data file to the
            # Lambda later means adding it here deliberately, which is the
            # intended cost.
            # The allowlist and the mode it is read under are module
            # constants (ASSET_EXCLUDE / ASSET_IGNORE_MODE, above) so the test
            # can assert the POLICY rather than a copy of it. A test carrying
            # its own copy of these patterns passes while the stack ships
            # something else.
            # Through the helper, not by hand: `ASSET_EXCLUDE` without
            # `ASSET_IGNORE_MODE` reads as correct and stages two files.
            code=asset_policy.python_source(),
            timeout=Duration.minutes(15), memory_size=1024,
            environment=reindex_env)
        corpus_bucket.grant_read(reindex)
        reindex.add_to_role_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"], resources=[collection.attr_arn]))

        # THE QUERY ROLE'S AOSS GRANT LIVES HERE, NOT IN core_stack. SPEC/05
        # asks for `aoss:APIAccessAll` scoped to the collection ARN; M04 could
        # only reach `collection/*` in this account and region, and said so:
        #
        #   "NOT pinned to a collection id, and that is a constraint rather
        #    than an oversight: the collection is created by the EPHEMERAL
        #    search stack, takes a fresh id on every `make up`, and this
        #    persistent stack is deployed before it exists."
        #
        # That reasoning is right about core_stack and wrong about the grant.
        # The constraint is dissolved by moving the statement to the stack that
        # HAS the id. `collection.attr_arn` is concrete here.
        #
        # It also fixes a lifetime bug nobody had named: the grant used to
        # OUTLIVE the collection. `make down` destroys the hot tier and the
        # internet-facing role kept standing permission to reach every
        # collection in the account — including ones belonging to other
        # projects here — for the days or weeks until the next `make up`.
        # Attached to this stack it is created and destroyed with the thing it
        # is about, so the permission exists exactly when the collection does.
        #
        # `mutable=True` is what makes this an AWS::IAM::Policy in THIS stack
        # attached to a role owned by the other one — the direction of the
        # dependency is unchanged, and core still never references search.
        query_role = iam.Role.from_role_arn(
            self, "QueryLambdaRole", query_lambda_role_arn, mutable=True)
        query_role.add_to_principal_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"], resources=[collection.attr_arn]))

        # AOSS data access is governed ONLY by this policy — an IAM principal
        # with aoss:APIAccessAll still gets 403 unless it is named here.
        #
        # The two Lambda roles are not sufficient, and this is a gap in
        # SPEC/02's Done-when rather than a convenience: `run_retrieval.py`
        # calls router.retrieve() IN-PROCESS, deliberately, so that a failure
        # means "the chunk never came back" and not "the model fumbled it".
        # In-process means it runs as the operator's own principal. Without an
        # opt-in for that principal, the AOSS half of criterion 1 cannot be
        # executed by the person the spec asks to execute it.
        #
        # Opt-in and empty by default, so a deploy that does not ask for it
        # grants nothing: `cdk deploy -c devPrincipalArn=arn:...:user/you`, or
        # REGDELTA_DEV_PRINCIPAL_ARN in the environment. `make up` passes the
        # caller's own STS identity.
        #
        # The operator's principal gets its OWN read-only statement below and is
        # deliberately NOT added to the aoss:* list. An earlier version appended
        # it here, which handed a human principal DeleteIndex and WriteDocument
        # on the corpus index to run a read-only eval harness, and deferred the
        # narrowing to the SPEC/05 write/read split. Security review of this
        # branch (M1) was right that a *new* widening must not ride out on an
        # existing TODO — and read-only for this one principal does not need the
        # SPEC/05 split, only a second statement with a different principal list.
        # SPLIT, not one list. The reindex role BUILDS the index — it creates,
        # writes and deletes documents — and the query role only reads it.
        #
        # They shared one `aoss:*` statement until M04 on the SPEC/05 write/read
        # deferral. That stopped being tenable when `core_stack` scoped the
        # query role's IAM grant to `collection/*` and justified the remaining
        # breadth by citing THIS policy as "the control that actually admits the
        # request" — a citation that was false while this granted it `aoss:*`.
        # The internet-facing role could DeleteIndex and WriteDocument on the
        # corpus index the cited deadlines are drawn from.
        #
        # The narrowing needed no SPEC/05 split after all, for the same reason
        # the operator's statement below did not: a second statement with a
        # different principal list. Security review of the M04 IAM scoping.
        index_writers = [reindex.role.role_arn]
        # src/retrieval/aoss_tier.py issues `_search` and `_msearch`, both
        # index-level reads, and nothing else — the same two permissions the
        # operator's read-only statement has been running the probe harness on.
        index_readers = [query_lambda_role_arn]
        dev_principal = (self.node.try_get_context("devPrincipalArn")
                         or os.environ.get("REGDELTA_DEV_PRINCIPAL_ARN"))
        if dev_principal:
            # Validate before it reaches a policy granting aoss:* on a
            # collection whose network policy is AllowFromPublic. Unvalidated, a
            # cross-account role ARN — one mistyped account id — grants read AND
            # write on the index built from the corpus, i.e. corpus data leaving
            # the account, reachable by a one-token mistake.
            m = _DEV_PRINCIPAL_RE.fullmatch(dev_principal)
            if not m:
                raise ValueError(
                    f"devPrincipalArn {dev_principal!r} is not an IAM user or "
                    "role ARN. Expected arn:aws:iam::<account>:user/NAME or "
                    ":role/NAME.\n"
                    "Note an assumed-role ARN "
                    "(arn:aws:sts::…:assumed-role/Role/session) is what `aws "
                    "sts get-caller-identity` returns under SSO or any assumed "
                    "role, and AOSS data-access policies do NOT match on it — "
                    "pass the underlying role ARN instead. A bare 403 with a "
                    "propagation-shaped message is the symptom otherwise.")
            # The cross-account check is only enforceable when the account is
            # concrete. With no CDK_DEFAULT_ACCOUNT, self.account is an
            # unresolved token, and an unchecked ARN would then be baked into the
            # cloud assembly for a later `cdk deploy --app cdk.out` to apply
            # against a collection whose network policy is AllowFromPublic. So
            # refuse rather than skip: this switch is only ever used from an
            # authenticated laptop, where the account resolves. Security review
            # of this branch, finding L2.
            if cdk.Token.is_unresolved(self.account):
                raise ValueError(
                    "devPrincipalArn requires a resolved account so the "
                    "cross-account check can run. Set CDK_DEFAULT_ACCOUNT or "
                    "synth with credentials. Refusing rather than skipping the "
                    "check: an unvalidated principal baked into cdk.out grants "
                    "access to the corpus index on a later deploy.")
            if m.group("account") != self.account:
                raise ValueError(
                    f"devPrincipalArn names account {m.group('account')}, not "
                    f"this account ({self.account}) — this switch does not "
                    "grant cross-account access to the corpus index")
            # Visible in the synth log. Unlike `-c devPrincipalArn=…`, the
            # REGDELTA_DEV_PRINCIPAL_ARN path leaves no trace in the deploy
            # command, and infra/cdk.context.json is gitignored — so a leftover
            # `export` would silently widen every `make up` with no artifact.
            # Security review of this branch, finding L3.
            cdk.Annotations.of(self).add_info(
                f"AOSS data access: granting READ-ONLY index access to "
                f"{dev_principal}")

        statements: list[dict] = [{
            "Rules": [
                {"ResourceType": "collection",
                 "Resource": [f"collection/{COLLECTION_NAME}"],
                 "Permission": ["aoss:*"]},
                {"ResourceType": "index",
                 "Resource": [f"index/{COLLECTION_NAME}/*"],
                 "Permission": ["aoss:*"]},
            ],
            "Principal": index_writers,
        }, {
            # INDEX-LEVEL ONLY. A collection-level rule would carry
            # CreateCollectionItems and DeleteCollectionItems, which is how a
            # read-only intent turns back into index deletion by another route.
            "Rules": [
                {"ResourceType": "index",
                 "Resource": [f"index/{COLLECTION_NAME}/*"],
                 "Permission": ["aoss:DescribeIndex", "aoss:ReadDocument"]},
            ],
            "Principal": index_readers,
        }]
        if dev_principal:
            # Read-only, and separate. The eval harness only ever issues
            # _search / _msearch / _count (src/retrieval/aoss_tier.py), all of
            # which are index-level reads — it never creates, writes or deletes.
            statements.append({
                "Rules": [
                    {"ResourceType": "index",
                     "Resource": [f"index/{COLLECTION_NAME}/*"],
                     "Permission": ["aoss:DescribeIndex", "aoss:ReadDocument"]},
                ],
                "Principal": [dev_principal],
            })

        access = aoss.CfnAccessPolicy(
            self, "DataAccessPolicy",
            name=f"{COLLECTION_NAME}-access", type="data",
            policy=json.dumps(statements))
        access.add_dependency(collection)

        triggers.Trigger(
            self, "HydrateOnDeploy",
            handler=reindex,
            execute_after=[access],
            execute_on_handler_change=True,
            # The Trigger's INVOCATION timeout, which defaults to 2 minutes and
            # is separate from the function's own 15. Hydration can legitimately
            # need longer than two minutes: AOSS exposes no refresh API, so the
            # count-parity assertion polls for up to 5 minutes, and the first
            # write after deploy waits out data-access-policy propagation. At
            # the default, a healthy deploy fails on the invoker's clock and
            # reports it as a hydration failure. Kept under the provider
            # handler's own 900s.
            timeout=Duration.minutes(14))

        ssm.StringParameter(
            self, "EndpointParam",
            parameter_name=SSM_ENDPOINT_PARAM,
            string_value=collection.attr_collection_endpoint)

        cdk.CfnOutput(self, "CollectionEndpoint",
                      value=collection.attr_collection_endpoint)
        cdk.CfnOutput(self, "SessionCostNote",
                      value="Dev mode ≈ $0.24/hr while this stack exists; "
                            "`make down` stops billing.")
