provider "aws" {
  region = "us-east-1"
}

resource "aws_ecs_cluster" "rag_cluster" {
  name = "enterprise-rag-copilot-cluster"
}

resource "aws_ecs_task_definition" "rag_task" {
  family                   = "rag-copilot-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024" # 1 vCPU
  memory                   = "2048" # 2 GB RAM
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn

  container_definitions = jsonencode([
    {
      name      = "rag-copilot-container"
      image     = "your-aws-account-id.dkr.ecr.us-east-1.amazonaws.com/rag-copilot:latest"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "UPSTASH_REDIS_HOST", value = "liberal-donkey-34567.upstash.io" },
        { name = "DB_URI", value = "postgresql://admin:secret@your-rds-endpoint:5432/postgres" }
      ]
    }
  ])
}

resource "aws_ecs_service" "rag_service" {
  name            = "rag-copilot-service"
  cluster         = aws_ecs_cluster.rag_cluster.id
  task_definition = aws_ecs_task_definition.rag_task.arn
  launch_type     = "FARGATE"
  desired_count   = 2

  network_configuration {
    subnets          = ["subnet-xxxxxx", "subnet-yyyyyy"]
    assign_public_ip = true
    security_groups  = ["sg-zzzzzz"]
  }
}