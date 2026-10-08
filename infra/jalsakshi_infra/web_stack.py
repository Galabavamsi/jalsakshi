"""WebStack: the operator console (S3 + CloudFront) and its Cognito user pool.

The console signs in with the Cognito managed login (authorization code + PKCE, public client,
no secret). Role groups mirror ``OperatorRole``; the API reads ``cognito:groups`` for Cedar.
"""

from __future__ import annotations

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

from jalsakshi.core.models import OperatorRole
from jalsakshi_infra.settings import REGION, StageSettings

CALLBACK_PATH = "/auth/callback"


class WebStack(cdk.Stack):
    """Static console hosting and operator sign-in."""

    def __init__(self, scope: Construct, cid: str, *, cfg: StageSettings, **kwargs: Any) -> None:
        super().__init__(scope, cid, **kwargs)
        self.site_bucket = s3.Bucket(
            self,
            "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        self.distribution = self._distribution(cfg)
        self.cdn_url = f"https://{self.distribution.distribution_domain_name}"
        self.web_url = f"https://{cfg.web_domain}" if self._custom_domain(cfg) else self.cdn_url
        self.user_pool = self._user_pool(cfg)
        self.domain = self.user_pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=cfg.auth_domain_prefix or f"jalsakshi-{cfg.stage}-{self.account}"
            ),
        )
        self.client = self._client(cfg)
        self._deploy_site(cfg)
        cdk.CfnOutput(self, "WebUrl", value=self.web_url)
        cdk.CfnOutput(self, "CdnDomain", value=self.distribution.distribution_domain_name)
        cdk.CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=self.client.user_pool_client_id)
        cdk.CfnOutput(
            self,
            "CognitoDomain",
            value=f"https://{self.domain.domain_name}.auth.{REGION}.amazoncognito.com",
        )

    @staticmethod
    def _custom_domain(cfg: StageSettings) -> bool:
        """A custom console domain needs both the name and a validated us-east-1 certificate."""
        return bool(cfg.web_domain and cfg.web_cert_arn)

    def _distribution(self, cfg: StageSettings) -> cloudfront.Distribution:
        domain: dict[str, Any] = {}
        if self._custom_domain(cfg):
            domain = {
                "domain_names": [cfg.web_domain],
                "certificate": acm.Certificate.from_certificate_arn(
                    self, "WebCertificate", str(cfg.web_cert_arn)
                ),
            }
        spa = [
            cloudfront.ErrorResponse(
                http_status=status,
                response_http_status=200,
                response_page_path="/index.html",
                ttl=cdk.Duration.seconds(0),
            )
            for status in (403, 404)
        ]
        return cloudfront.Distribution(
            self,
            "SiteCdn",
            comment=f"JalSakshi {cfg.stage} console",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
            ),
            error_responses=spa,
            price_class=cloudfront.PriceClass.PRICE_CLASS_200,
            **domain,
        )

    def _user_pool(self, cfg: StageSettings) -> cognito.UserPool:
        pool = cognito.UserPool(
            self,
            "Operators",
            user_pool_name=cfg.name("operators"),
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True, email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_digits=True,
                require_lowercase=True,
                require_uppercase=True,
                require_symbols=False,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=cfg.removal_policy,
        )
        for role in OperatorRole:
            cognito.CfnUserPoolGroup(
                self,
                f"Group{role.value}",
                user_pool_id=pool.user_pool_id,
                group_name=role.value,
                description=f"Console users acting as {role.value}",
            )
        return pool

    def _client(self, cfg: StageSettings) -> cognito.UserPoolClient:
        origins_ = list(dict.fromkeys([self.web_url, self.cdn_url, *cfg.local_origins]))
        return self.user_pool.add_client(
            "Console",
            user_pool_client_name=cfg.name("console"),
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[f"{origin}{CALLBACK_PATH}" for origin in origins_],
                logout_urls=[f"{origin}/" for origin in origins_],
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
            access_token_validity=cdk.Duration.hours(1),
            id_token_validity=cdk.Duration.hours(1),
            refresh_token_validity=cdk.Duration.days(7),
        )

    def _deploy_site(self, cfg: StageSettings) -> None:
        """Upload web/dist when it exists (build the console first; see the deploy notes)."""
        if not (cfg.web_dist / "index.html").is_file():
            cdk.Annotations.of(self).add_warning_v2(
                "jalsakshi:web-dist-missing",
                f"{cfg.web_dist} has no index.html; the console is not uploaded. "
                "Build web/ (pnpm build) and deploy this stack again.",
            )
            return
        s3deploy.BucketDeployment(
            self,
            "DeploySite",
            sources=[s3deploy.Source.asset(str(cfg.web_dist))],
            destination_bucket=self.site_bucket,
            distribution=self.distribution,
            distribution_paths=["/*"],
            memory_limit=512,
        )
