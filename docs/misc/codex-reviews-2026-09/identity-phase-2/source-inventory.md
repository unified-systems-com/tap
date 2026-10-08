# Pinned source inventory

Core: `tap` at `a6581ada042a61da8f3dbb3791b34066991d6c14`.

Counts are static concrete ENTITY_TYPE declarations, excluding tests, migrations and fixture directories.

## dcom-tap

Commit: [2f22397592c79ea5a190f866d26a0ec8c30eb41d](https://github.com/unified-systems-com/dcom-tap/tree/2f22397592c79ea5a190f866d26a0ec8c30eb41d)


## git-core-tap

Commit: [e3675d1ccb17c40bf1d1527db3fb765865adef17](https://github.com/unified-systems-com/git-core-tap/tree/e3675d1ccb17c40bf1d1527db3fb765865adef17)

- [tap_plugin/git_core/models/git_ref.py:26](https://github.com/unified-systems-com/git-core-tap/blob/e3675d1ccb17c40bf1d1527db3fb765865adef17/tap_plugin/git_core/models/git_ref.py#L26) — `ENTITY_TYPE: ClassVar[str] = "git_core__git_ref"`
- [tap_plugin/git_core/models/git_commit.py:32](https://github.com/unified-systems-com/git-core-tap/blob/e3675d1ccb17c40bf1d1527db3fb765865adef17/tap_plugin/git_core/models/git_commit.py#L32) — `ENTITY_TYPE: ClassVar[str] = "git_core__git_commit"`
- [tap_plugin/git_core/models/git_repository.py:23](https://github.com/unified-systems-com/git-core-tap/blob/e3675d1ccb17c40bf1d1527db3fb765865adef17/tap_plugin/git_core/models/git_repository.py#L23) — `ENTITY_TYPE: ClassVar[str] = "git_core__git_repository"`

## git-serious-double-tap

Commit: [8e2ebcf52f6776881fe705ffad3139cc2420f9ad](https://github.com/unified-systems-com/git-serious-double-tap/tree/8e2ebcf52f6776881fe705ffad3139cc2420f9ad)


## git-serious-tap

Commit: [575fcc468b0cd7fcba064559d297cd9630bd0074](https://github.com/unified-systems-com/git-serious-tap/tree/575fcc468b0cd7fcba064559d297cd9630bd0074)


## tap-plugin-administrivia

Commit: [b9a8f2377447579a3819ce4af7988ad28b49cd9e](https://github.com/unified-systems-com/tap-plugin-administrivia/tree/b9a8f2377447579a3819ce4af7988ad28b49cd9e)


## tap-plugin-aws-core

Commit: [bc0cac57ab6815a4319fc60733124a99de4dd770](https://github.com/unified-systems-com/tap-plugin-aws-core/tree/bc0cac57ab6815a4319fc60733124a99de4dd770)

- [tap_plugin/aws_core/models/cloudwatch_log_group.py:24](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/cloudwatch_log_group.py#L24) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudwatch_log_group"`
- [tap_plugin/aws_core/models/elasticache_cluster.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/elasticache_cluster.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_elasticache_cluster"`
- [tap_plugin/aws_core/models/vpc.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/vpc.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_vpc"`
- [tap_plugin/aws_core/models/route_table.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/route_table.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_route_table"`
- [tap_plugin/aws_core/models/cloudfront_distribution.py:21](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/cloudfront_distribution.py#L21) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudfront_distribution"`
- [tap_plugin/aws_core/models/subnet.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/subnet.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_subnet"`
- [tap_plugin/aws_core/models/iam_role.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/iam_role.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_role"`
- [tap_plugin/aws_core/models/alb.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/alb.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_alb"`
- [tap_plugin/aws_core/models/internet_gateway.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/internet_gateway.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_internet_gateway"`
- [tap_plugin/aws_core/models/aws_region.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/aws_region.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_region"`
- [tap_plugin/aws_core/models/s3_bucket.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/s3_bucket.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_s3_bucket"`
- [tap_plugin/aws_core/models/eks_cluster.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/eks_cluster.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_eks_cluster"`
- [tap_plugin/aws_core/models/iam_oidc_provider.py:23](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/iam_oidc_provider.py#L23) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_oidc_provider"`
- [tap_plugin/aws_core/models/dynamodb_table.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/dynamodb_table.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_dynamodb_table"`
- [tap_plugin/aws_core/models/rds_instance.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/rds_instance.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_instance"`
- [tap_plugin/aws_core/models/cognito_user_pool.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/cognito_user_pool.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cognito_user_pool"`
- [tap_plugin/aws_core/models/secrets_manager_secret.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/secrets_manager_secret.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_secrets_manager_secret"`
- [tap_plugin/aws_core/models/ecs_service.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/ecs_service.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ecs_service"`
- [tap_plugin/aws_core/models/sqs_queue.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/sqs_queue.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_sqs_queue"`
- [tap_plugin/aws_core/models/iam_user.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/iam_user.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_user"`
- [tap_plugin/aws_core/models/target_group.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/target_group.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_target_group"`
- [tap_plugin/aws_core/models/acm_certificate.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/acm_certificate.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_acm_certificate"`
- [tap_plugin/aws_core/models/nat_gateway.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/nat_gateway.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_nat_gateway"`
- [tap_plugin/aws_core/models/kms_key.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/kms_key.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_kms_key"`
- [tap_plugin/aws_core/models/eventbridge_rule.py:22](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/eventbridge_rule.py#L22) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_eventbridge_rule"`
- [tap_plugin/aws_core/models/route53_hosted_zone.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/route53_hosted_zone.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_route53_zone"`
- [tap_plugin/aws_core/models/network_firewall.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/network_firewall.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_network_firewall"`
- [tap_plugin/aws_core/models/ecr_repository.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/ecr_repository.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ecr_repository"`
- [tap_plugin/aws_core/models/aws_account.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/aws_account.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_account"`
- [tap_plugin/aws_core/models/bedrock_model.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/bedrock_model.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_bedrock_model"`
- [tap_plugin/aws_core/models/apigateway_http_api.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/apigateway_http_api.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigateway_http_api"`
- [tap_plugin/aws_core/models/ebs_volume.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/ebs_volume.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ebs_volume"`
- [tap_plugin/aws_core/models/sagemaker_endpoint.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/sagemaker_endpoint.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_sagemaker_endpoint"`
- [tap_plugin/aws_core/models/elastic_ip.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/elastic_ip.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_elastic_ip"`
- [tap_plugin/aws_core/models/iam_policy.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/iam_policy.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_policy"`
- [tap_plugin/aws_core/models/cloudtrail_trail.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/cloudtrail_trail.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudtrail_trail"`
- [tap_plugin/aws_core/models/elb.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/elb.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_elb"`
- [tap_plugin/aws_core/models/elasticsearch_domain.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/elasticsearch_domain.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_elasticsearch_domain"`
- [tap_plugin/aws_core/models/security_group.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/security_group.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_security_group"`
- [tap_plugin/aws_core/models/ec2_instance.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/ec2_instance.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ec2_instance"`
- [tap_plugin/aws_core/models/ssm_parameter.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/ssm_parameter.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ssm_parameter"`
- [tap_plugin/aws_core/models/lambda_function.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/lambda_function.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_lambda"`
- [tap_plugin/aws_core/models/ecs_cluster.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/ecs_cluster.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ecs_cluster"`
- [tap_plugin/aws_core/models/availability_zone.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/availability_zone.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_az"`
- [tap_plugin/aws_core/models/ecs_task.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/ecs_task.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ecs_task"`
- [tap_plugin/aws_core/models/network_acl.py:13](https://github.com/unified-systems-com/tap-plugin-aws-core/blob/bc0cac57ab6815a4319fc60733124a99de4dd770/tap_plugin/aws_core/models/network_acl.py#L13) — `ENTITY_TYPE: ClassVar[str] = "aws_core__aws_network_acl"`

## tap-plugin-compliance-core

Commit: [f50d9931e51f32f656d7e3add96fd3707bbbdba5](https://github.com/unified-systems-com/tap-plugin-compliance-core/tree/f50d9931e51f32f656d7e3add96fd3707bbbdba5)

- [tap_plugin/compliance_core/models/compliance_context.py:40](https://github.com/unified-systems-com/tap-plugin-compliance-core/blob/f50d9931e51f32f656d7e3add96fd3707bbbdba5/tap_plugin/compliance_core/models/compliance_context.py#L40) — `ENTITY_TYPE: ClassVar[str] = "compliance_core__compliance_context"`
- [tap_plugin/compliance_core/models/compliance_evidence.py:25](https://github.com/unified-systems-com/tap-plugin-compliance-core/blob/f50d9931e51f32f656d7e3add96fd3707bbbdba5/tap_plugin/compliance_core/models/compliance_evidence.py#L25) — `ENTITY_TYPE: ClassVar[str] = "compliance_core__compliance_evidence"`
- [tap_plugin/compliance_core/models/compliance_artifact.py:27](https://github.com/unified-systems-com/tap-plugin-compliance-core/blob/f50d9931e51f32f656d7e3add96fd3707bbbdba5/tap_plugin/compliance_core/models/compliance_artifact.py#L27) — `ENTITY_TYPE: ClassVar[str] = "compliance_core__compliance_artifact"`
- [tap_plugin/compliance_core/models/compliance_finding.py:25](https://github.com/unified-systems-com/tap-plugin-compliance-core/blob/f50d9931e51f32f656d7e3add96fd3707bbbdba5/tap_plugin/compliance_core/models/compliance_finding.py#L25) — `ENTITY_TYPE: ClassVar[str] = "compliance_core__compliance_finding"`
- [tap_plugin/compliance_core/models/compliance_boundary.py:29](https://github.com/unified-systems-com/tap-plugin-compliance-core/blob/f50d9931e51f32f656d7e3add96fd3707bbbdba5/tap_plugin/compliance_core/models/compliance_boundary.py#L29) — `ENTITY_TYPE: ClassVar[str] = "compliance_core__compliance_boundary"`
- [tap_plugin/compliance_core/models/compliance_exception.py:28](https://github.com/unified-systems-com/tap-plugin-compliance-core/blob/f50d9931e51f32f656d7e3add96fd3707bbbdba5/tap_plugin/compliance_core/models/compliance_exception.py#L28) — `ENTITY_TYPE: ClassVar[str] = "compliance_core__compliance_exception"`

## tap-plugin-computing-core

Commit: [f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5](https://github.com/unified-systems-com/tap-plugin-computing-core/tree/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5)

- [tap_plugin/computing_core/models/port.py:13](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/port.py#L13) — `ENTITY_TYPE: ClassVar[str] = "computing_core__port"`
- [tap_plugin/computing_core/models/user.py:22](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/user.py#L22) — `ENTITY_TYPE: ClassVar[str] = "computing_core__user"`
- [tap_plugin/computing_core/models/private_key.py:13](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/private_key.py#L13) — `ENTITY_TYPE: ClassVar[str] = "computing_core__private_key"`
- [tap_plugin/computing_core/models/network_interface.py:13](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/network_interface.py#L13) — `ENTITY_TYPE: ClassVar[str] = "computing_core__network_interface"`
- [tap_plugin/computing_core/models/web_host.py:21](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/web_host.py#L21) — `ENTITY_TYPE: ClassVar[str] = "computing_core__web_host"`
- [tap_plugin/computing_core/models/tcp_connection.py:13](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/tcp_connection.py#L13) — `ENTITY_TYPE: ClassVar[str] = "computing_core__tcp_connection"`
- [tap_plugin/computing_core/models/file.py:13](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/file.py#L13) — `ENTITY_TYPE: ClassVar[str] = "computing_core__file"`
- [tap_plugin/computing_core/models/program.py:13](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/program.py#L13) — `ENTITY_TYPE: ClassVar[str] = "computing_core__program"`
- [tap_plugin/computing_core/models/ip_address.py:13](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/ip_address.py#L13) — `ENTITY_TYPE: ClassVar[str] = "computing_core__ip_address"`
- [tap_plugin/computing_core/models/web_document.py:21](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/web_document.py#L21) — `ENTITY_TYPE: ClassVar[str] = "computing_core__web_document"`
- [tap_plugin/computing_core/models/public_key.py:13](https://github.com/unified-systems-com/tap-plugin-computing-core/blob/f144d6dd84ddee3fea4c9dbe2d0dfb44fe7bf4e5/tap_plugin/computing_core/models/public_key.py#L13) — `ENTITY_TYPE: ClassVar[str] = "computing_core__public_key"`

## tap-plugin-fedramp-20x-ksi

Commit: [d4fe84437a7008d43d0110ed7d1314899b67f174](https://github.com/unified-systems-com/tap-plugin-fedramp-20x-ksi/tree/d4fe84437a7008d43d0110ed7d1314899b67f174)

- [tap_plugin/fedramp_20x_ksi/models/ksi_validation.py:22](https://github.com/unified-systems-com/tap-plugin-fedramp-20x-ksi/blob/d4fe84437a7008d43d0110ed7d1314899b67f174/tap_plugin/fedramp_20x_ksi/models/ksi_validation.py#L22) — `ENTITY_TYPE: ClassVar[str] = "fedramp_20x_ksi__ksi_validation"`
- [tap_plugin/fedramp_20x_ksi/models/ksi_signal.py:23](https://github.com/unified-systems-com/tap-plugin-fedramp-20x-ksi/blob/d4fe84437a7008d43d0110ed7d1314899b67f174/tap_plugin/fedramp_20x_ksi/models/ksi_signal.py#L23) — `ENTITY_TYPE: ClassVar[str] = "fedramp_20x_ksi__ksi_signal"`
- [tap_plugin/fedramp_20x_ksi/models/ksi_indicator.py:13](https://github.com/unified-systems-com/tap-plugin-fedramp-20x-ksi/blob/d4fe84437a7008d43d0110ed7d1314899b67f174/tap_plugin/fedramp_20x_ksi/models/ksi_indicator.py#L13) — `ENTITY_TYPE: ClassVar[str] = "fedramp_20x_ksi__ksi_indicator"`
- [tap_plugin/fedramp_20x_ksi/models/ksi_violation.py:27](https://github.com/unified-systems-com/tap-plugin-fedramp-20x-ksi/blob/d4fe84437a7008d43d0110ed7d1314899b67f174/tap_plugin/fedramp_20x_ksi/models/ksi_violation.py#L27) — `ENTITY_TYPE: ClassVar[str] = "fedramp_20x_ksi__ksi_violation"`
- [tap_plugin/fedramp_20x_ksi/models/vdr_finding.py:26](https://github.com/unified-systems-com/tap-plugin-fedramp-20x-ksi/blob/d4fe84437a7008d43d0110ed7d1314899b67f174/tap_plugin/fedramp_20x_ksi/models/vdr_finding.py#L26) — `ENTITY_TYPE: ClassVar[str] = "fedramp_20x_ksi__vdr_finding"`
- [tap_plugin/fedramp_20x_ksi/models/vdr_report.py:21](https://github.com/unified-systems-com/tap-plugin-fedramp-20x-ksi/blob/d4fe84437a7008d43d0110ed7d1314899b67f174/tap_plugin/fedramp_20x_ksi/models/vdr_report.py#L21) — `ENTITY_TYPE: ClassVar[str] = "fedramp_20x_ksi__vdr_report"`
- [tap_plugin/fedramp_20x_ksi/models/ksi_component.py:22](https://github.com/unified-systems-com/tap-plugin-fedramp-20x-ksi/blob/d4fe84437a7008d43d0110ed7d1314899b67f174/tap_plugin/fedramp_20x_ksi/models/ksi_component.py#L22) — `ENTITY_TYPE: ClassVar[str] = "fedramp_20x_ksi__ksi_component"`
- [tap_plugin/fedramp_20x_ksi/models/ksi_theme.py:13](https://github.com/unified-systems-com/tap-plugin-fedramp-20x-ksi/blob/d4fe84437a7008d43d0110ed7d1314899b67f174/tap_plugin/fedramp_20x_ksi/models/ksi_theme.py#L13) — `ENTITY_TYPE: ClassVar[str] = "fedramp_20x_ksi__ksi_theme"`

## tap-plugin-github-core

Commit: [4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211](https://github.com/unified-systems-com/tap-plugin-github-core/tree/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211)

- [tap_plugin/github_core/models/actions_artifact.py:35](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/actions_artifact.py#L35) — `ENTITY_TYPE: ClassVar[str] = "github_core__actions_artifact"`
- [tap_plugin/github_core/models/github_package_version.py:21](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_package_version.py#L21) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_package_version"`
- [tap_plugin/github_core/models/github_package.py:24](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_package.py#L24) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_package"`
- [tap_plugin/github_core/models/status_check.py:32](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/status_check.py#L32) — `ENTITY_TYPE: ClassVar[str] = "github_core__status_check"`
- [tap_plugin/github_core/models/github_actions_job.py:20](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_actions_job.py#L20) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_actions_job"`
- [tap_plugin/github_core/models/github_ruleset.py:31](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_ruleset.py#L31) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_ruleset"`
- [tap_plugin/github_core/models/pull_request.py:28](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/pull_request.py#L28) — `ENTITY_TYPE: ClassVar[str] = "github_core__pull_request"`
- [tap_plugin/github_core/models/workflow_job.py:30](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/workflow_job.py#L30) — `ENTITY_TYPE: ClassVar[str] = "github_core__workflow_job"`
- [tap_plugin/github_core/models/github_release.py:26](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_release.py#L26) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_release"`
- [tap_plugin/github_core/models/collection_scope.py:292](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/collection_scope.py#L292) — `ENTITY_TYPE: ClassVar[str] = "github_core__collection_scope"`
- [tap_plugin/github_core/models/github_actions_run.py:19](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_actions_run.py#L19) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_actions_run"`
- [tap_plugin/github_core/models/github_app.py:29](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_app.py#L29) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_app"`
- [tap_plugin/github_core/models/app_installation.py:27](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/app_installation.py#L27) — `ENTITY_TYPE: ClassVar[str] = "github_core__app_installation"`
- [tap_plugin/github_core/models/github_custom_property.py:31](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_custom_property.py#L31) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_custom_property"`
- [tap_plugin/github_core/models/actions_secret.py:35](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/actions_secret.py#L35) — `ENTITY_TYPE: ClassVar[str] = "github_core__actions_secret"`
- [tap_plugin/github_core/models/commit_observation.py:26](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/commit_observation.py#L26) — `ENTITY_TYPE: ClassVar[str] = "github_core__commit_observation"`
- [tap_plugin/github_core/models/github_environment.py:21](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_environment.py#L21) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_environment"`
- [tap_plugin/github_core/models/github_runner.py:21](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_runner.py#L21) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_runner"`
- [tap_plugin/github_core/models/rule_suite.py:37](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/rule_suite.py#L37) — `ENTITY_TYPE: ClassVar[str] = "github_core__rule_suite"`
- [tap_plugin/github_core/models/github_platform.py:22](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_platform.py#L22) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_platform"`
- [tap_plugin/github_core/models/actions_cache.py:29](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/actions_cache.py#L29) — `ENTITY_TYPE: ClassVar[str] = "github_core__actions_cache"`
- [tap_plugin/github_core/models/code_scanning_alert.py:34](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/code_scanning_alert.py#L34) — `ENTITY_TYPE: ClassVar[str] = "github_core__code_scanning_alert"`
- [tap_plugin/github_core/models/code_scanning_analysis.py:27](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/code_scanning_analysis.py#L27) — `ENTITY_TYPE: ClassVar[str] = "github_core__code_scanning_analysis"`
- [tap_plugin/github_core/models/github_workflow.py:20](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_workflow.py#L20) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_workflow"`
- [tap_plugin/github_core/models/github_action.py:34](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_action.py#L34) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_action"`
- [tap_plugin/github_core/models/github_account.py:16](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_account.py#L16) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_account"`
- [tap_plugin/github_core/models/github_repository.py:16](https://github.com/unified-systems-com/tap-plugin-github-core/blob/4f1cb7fbbc7f2dfdeb5da7a19b07fc8d3cf7c211/tap_plugin/github_core/models/github_repository.py#L16) — `ENTITY_TYPE: ClassVar[str] = "github_core__github_repository"`

## tap-plugin-grid-fixtures

Commit: [585c35c7f8cf2ada8dc4d3c64037eea50b9477fb](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/tree/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb)

- [tap_plugin/grid_fixtures/models/dual_endpoint.py:28](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/dual_endpoint.py#L28) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__dual_endpoint"`
- [tap_plugin/grid_fixtures/models/pg_hub.py:31](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/pg_hub.py#L31) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__hub"`
- [tap_plugin/grid_fixtures/models/outbound_blocked.py:28](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/outbound_blocked.py#L28) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__outbound_blocked"`
- [tap_plugin/grid_fixtures/models/pg_node.py:31](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/pg_node.py#L31) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__node"`
- [tap_plugin/grid_fixtures/models/peer_group.py:28](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/peer_group.py#L28) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__peer_group"`
- [tap_plugin/grid_fixtures/models/exclusive_field.py:46](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/exclusive_field.py#L46) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__exclusive_field"`
- [tap_plugin/grid_fixtures/models/inbound_blocked.py:28](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/inbound_blocked.py#L28) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__inbound_blocked"`
- [tap_plugin/grid_fixtures/models/pg_cycle_node.py:31](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/pg_cycle_node.py#L31) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__cycle_node"`
- [tap_plugin/grid_fixtures/models/pg_leaf.py:31](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/pg_leaf.py#L31) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__leaf"`
- [tap_plugin/grid_fixtures/models/constrained_source.py:28](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/constrained_source.py#L28) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__constrained_source"`
- [tap_plugin/grid_fixtures/models/wildcard_referencer.py:28](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/wildcard_referencer.py#L28) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__wildcard_referencer"`
- [tap_plugin/grid_fixtures/models/unconstrained.py:28](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/unconstrained.py#L28) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__unconstrained"`
- [tap_plugin/grid_fixtures/models/constrained_target.py:28](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/constrained_target.py#L28) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__constrained_target"`
- [tap_plugin/grid_fixtures/models/nesting_container.py:28](https://github.com/unified-systems-com/tap-plugin-grid-fixtures/blob/585c35c7f8cf2ada8dc4d3c64037eea50b9477fb/tap_plugin/grid_fixtures/models/nesting_container.py#L28) — `ENTITY_TYPE: ClassVar[str] = "grid_fixtures__nesting_container"`

## tap-plugin-gryphon-playground

Commit: [8eb53dc3cfe4aefdfa9f25d99bb69ae2023cb624](https://github.com/unified-systems-com/tap-plugin-gryphon-playground/tree/8eb53dc3cfe4aefdfa9f25d99bb69ae2023cb624)


## tap-plugin-identity-core

Commit: [b56983a836f88858494c2afc18b76fa63b6b3592](https://github.com/unified-systems-com/tap-plugin-identity-core/tree/b56983a836f88858494c2afc18b76fa63b6b3592)

- [tap_plugin/identity_core/models/oidc_issuer.py:35](https://github.com/unified-systems-com/tap-plugin-identity-core/blob/b56983a836f88858494c2afc18b76fa63b6b3592/tap_plugin/identity_core/models/oidc_issuer.py#L35) — `ENTITY_TYPE: ClassVar[str] = "identity_core__oidc_issuer"`

## tap-plugin-roscale

Commit: [fd9d51f19ad9ba2667f73eb0800cb043dcc14210](https://github.com/unified-systems-com/tap-plugin-roscale/tree/fd9d51f19ad9ba2667f73eb0800cb043dcc14210)


## tap-plugin-samsite

Commit: [d81b9e9fb74049fbf9b4b8cf4d86d7dc94f22a95](https://github.com/unified-systems-com/tap-plugin-samsite/tree/d81b9e9fb74049fbf9b4b8cf4d86d7dc94f22a95)


## tap-plugin-sigstore-core

Commit: [40df07e16f66f1e6238b92b4ec60eb3fdc7f42e5](https://github.com/unified-systems-com/tap-plugin-sigstore-core/tree/40df07e16f66f1e6238b92b4ec60eb3fdc7f42e5)

- [tap_plugin/sigstore_core/models/rekor_log_entry.py:31](https://github.com/unified-systems-com/tap-plugin-sigstore-core/blob/40df07e16f66f1e6238b92b4ec60eb3fdc7f42e5/tap_plugin/sigstore_core/models/rekor_log_entry.py#L31) — `ENTITY_TYPE: ClassVar[str] = "sigstore_core__rekor_log_entry"`
- [tap_plugin/sigstore_core/models/sigstore_ca.py:26](https://github.com/unified-systems-com/tap-plugin-sigstore-core/blob/40df07e16f66f1e6238b92b4ec60eb3fdc7f42e5/tap_plugin/sigstore_core/models/sigstore_ca.py#L26) — `ENTITY_TYPE: ClassVar[str] = "sigstore_core__sigstore_ca"`

## zizmor-tap

Commit: [6f6e1406a1c2965c56fe075e761da6bc8939e65c](https://github.com/unified-systems-com/zizmor-tap/tree/6f6e1406a1c2965c56fe075e761da6bc8939e65c)

- [tap_plugin/zizmor/models/finding.py:77](https://github.com/unified-systems-com/zizmor-tap/blob/6f6e1406a1c2965c56fe075e761da6bc8939e65c/tap_plugin/zizmor/models/finding.py#L77) — `ENTITY_TYPE: ClassVar[str] = "zizmor__finding"`
- [tap_plugin/zizmor/models/run.py:30](https://github.com/unified-systems-com/zizmor-tap/blob/6f6e1406a1c2965c56fe075e761da6bc8939e65c/tap_plugin/zizmor/models/run.py#L30) — `ENTITY_TYPE: ClassVar[str] = "zizmor__run"`
