"""ObsStack: the ``JalSakshi-{stage}`` dashboard (§12 metrics) and alarms on every DLQ and on
errors of the IVR Lambda, published to an SNS topic."""

from __future__ import annotations

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from constructs import Construct

from jalsakshi_infra.app_stack import AppStack
from jalsakshi_infra.settings import StageSettings

NAMESPACE = "JalSakshi"
SERVICE = {"service": "jalsakshi"}
FIVE_MIN = cdk.Duration.minutes(5)


def app_metric(name: str, label: str | None = None) -> cw.Metric:
    """A JalSakshi EMF metric (Powertools adds the ``service`` dimension)."""
    return cw.Metric(
        namespace=NAMESPACE,
        metric_name=name,
        dimensions_map=SERVICE,
        statistic="Sum",
        period=FIVE_MIN,
        label=label or name,
    )


def by_dimension(name: str, dimension: str, period: cdk.Duration = FIVE_MIN) -> cw.MathExpression:
    """One line per value of ``dimension`` (e.g. each DayStatus or policy id)."""
    seconds = int(period.to_seconds())
    return cw.MathExpression(
        expression=(
            f"SEARCH('{{{NAMESPACE},service,{dimension}}} MetricName=\"{name}\"', 'Sum', {seconds})"
        ),
        using_metrics={},
        label=name,
        period=period,
    )


class ObsStack(cdk.Stack):
    """Dashboard and alarms for one stage."""

    def __init__(
        self, scope: Construct, cid: str, *, cfg: StageSettings, app: AppStack, **kwargs: Any
    ) -> None:
        super().__init__(scope, cid, **kwargs)
        self.topic = sns.Topic(self, "Alarms", topic_name=cfg.name("alarms"))
        if cfg.alarm_email:
            self.topic.add_subscription(subscriptions.EmailSubscription(cfg.alarm_email))
        self.dashboard = cw.Dashboard(
            self, "Dashboard", dashboard_name=f"JalSakshi-{cfg.stage}", widgets=self._widgets(app)
        )
        self._alarms(cfg, app)
        cdk.CfnOutput(self, "DashboardName", value=f"JalSakshi-{cfg.stage}")
        cdk.CfnOutput(self, "AlarmTopicArn", value=self.topic.topic_arn)

    def _widgets(self, app: AppStack) -> list[list[cw.IWidget]]:
        ivr, api = app.functions["Ivr"], app.functions["Api"]
        workflows = [app.checkin_run, app.ticket_flow]
        return [
            [
                cw.TextWidget(
                    markdown="# JalSakshi: household-verified tap water\n"
                    "Calls, day statuses, tickets and Cedar denies. PHED escalation is "
                    "**simulated**.",
                    width=24,
                    height=2,
                )
            ],
            [
                cw.GraphWidget(
                    title="Calls",
                    left=[
                        app_metric("CallsPlaced"),
                        app_metric("CallsAnswered"),
                        app_metric("CallsUnreachable"),
                    ],
                    width=8,
                ),
                cw.GraphWidget(
                    title="Day status (per village-day)",
                    left=[by_dimension("DayStatus", "status", cdk.Duration.hours(1))],
                    width=8,
                ),
                cw.GraphWidget(
                    title="Tickets",
                    left=[app_metric("TicketsOpened"), app_metric("TicketsClosedVerified")],
                    width=8,
                ),
            ],
            [
                cw.GraphWidget(
                    title="Cedar denies by policy",
                    left=[by_dimension("PolicyDenied", "policy_id")],
                    width=8,
                ),
                cw.GraphWidget(
                    title="Brief: template fallbacks",
                    left=[app_metric("AgentFallbackUsed")],
                    width=8,
                ),
                cw.GraphWidget(
                    title="Workflows",
                    left=[
                        m for sm in workflows for m in (sm.metric_succeeded(), sm.metric_failed())
                    ],
                    width=8,
                ),
            ],
            [
                cw.GraphWidget(
                    title="IVR and API Lambdas",
                    left=[ivr.metric_errors(), api.metric_errors()],
                    right=[ivr.metric_duration(), api.metric_duration()],
                    width=12,
                ),
                cw.GraphWidget(
                    title="Dead-letter queues",
                    left=[q.metric_approximate_number_of_messages_visible() for q in app.queues],
                    width=12,
                ),
            ],
        ]

    def _alarms(self, cfg: StageSettings, app: AppStack) -> None:
        action = cw_actions.SnsAction(self.topic)
        for queue in app.queues:
            alarm = cw.Alarm(
                self,
                f"{queue.node.id}NotEmpty",
                alarm_name=cfg.name(f"{queue.node.id.lower()}-not-empty"),
                metric=queue.metric_approximate_number_of_messages_visible(
                    period=cdk.Duration.minutes(1), statistic="Maximum"
                ),
                threshold=0,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
                evaluation_periods=1,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )
            alarm.add_alarm_action(action)
        ivr_errors = cw.Alarm(
            self,
            "IvrErrors",
            alarm_name=cfg.name("ivr-errors"),
            metric=app.functions["Ivr"].metric_errors(period=cdk.Duration.minutes(1)),
            threshold=0,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        ivr_errors.add_alarm_action(action)
