"""DataStack: the single DynamoDB table, the prompt-audio bucket behind CloudFront, and the
private evidence bucket (consented notes, context cache, evidence sheets)."""

from __future__ import annotations

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from jalsakshi.store.table import TABLE_SPEC
from jalsakshi_infra.settings import StageSettings

AUDIO_PREFIX = "prompts/hi"


def _attr(name: str) -> dynamodb.Attribute:
    kinds = {"S": dynamodb.AttributeType.STRING, "N": dynamodb.AttributeType.NUMBER}
    return dynamodb.Attribute(name=name, type=kinds[TABLE_SPEC["key_type"]])


class DataStack(cdk.Stack):
    """Storage that outlives code deploys."""

    def __init__(self, scope: Construct, cid: str, *, cfg: StageSettings, **kwargs: Any) -> None:
        super().__init__(scope, cid, **kwargs)
        self.table = self._table(cfg)
        self.prompts_bucket = self._bucket("PromptsBucket", cfg)
        self.evidence_bucket = self._bucket("EvidenceBucket", cfg)
        self.prompts_cdn = cloudfront.Distribution(
            self,
            "PromptsCdn",
            comment=f"JalSakshi {cfg.stage} prompt audio",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.prompts_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            price_class=cloudfront.PriceClass.PRICE_CLASS_200,
        )
        self.audio_base_url = f"https://{self.prompts_cdn.distribution_domain_name}/{AUDIO_PREFIX}"
        ssm.StringParameter(
            self,
            "PromptsBucketParam",
            parameter_name=f"{cfg.ssm_prefix}prompts_bucket",
            string_value=self.prompts_bucket.bucket_name,
            description="Bucket that prompts/render.py uploads Hindi prompt audio to",
        )
        cdk.CfnOutput(self, "TableName", value=self.table.table_name)
        cdk.CfnOutput(self, "PromptsBucketName", value=self.prompts_bucket.bucket_name)
        cdk.CfnOutput(self, "EvidenceBucketName", value=self.evidence_bucket.bucket_name)
        cdk.CfnOutput(self, "AudioBaseUrl", value=self.audio_base_url)

    def _table(self, cfg: StageSettings) -> dynamodb.TableV2:
        """The table exactly as ``store.table.TABLE_SPEC`` describes it."""
        gsis = [
            dynamodb.GlobalSecondaryIndexPropsV2(
                index_name=g["index_name"],
                partition_key=_attr(g["partition_key"]),
                sort_key=_attr(g["sort_key"]),
                projection_type=dynamodb.ProjectionType[g["projection"]],
            )
            for g in TABLE_SPEC["global_secondary_indexes"]
        ]
        pitr = dynamodb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=bool(TABLE_SPEC["point_in_time_recovery"])
        )
        return dynamodb.TableV2(
            self,
            "Table",
            table_name=cfg.table_name,
            partition_key=_attr(TABLE_SPEC["partition_key"]),
            sort_key=_attr(TABLE_SPEC["sort_key"]),
            billing=dynamodb.Billing.on_demand(),
            global_secondary_indexes=gsis,
            time_to_live_attribute=TABLE_SPEC["ttl_attribute"],
            point_in_time_recovery_specification=pitr,
            deletion_protection=not cfg.is_dev,
            removal_policy=cfg.removal_policy,
        )

    def _bucket(self, cid: str, cfg: StageSettings) -> s3.Bucket:
        return s3.Bucket(
            self,
            cid,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=not cfg.is_dev,
            removal_policy=cfg.removal_policy,
            auto_delete_objects=cfg.is_dev,
        )
