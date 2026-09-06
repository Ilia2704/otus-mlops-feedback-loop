.PHONY: up infra images apps status ports ports-status ports-stop kube-ui reset check evaluate data destroy

up: infra images apps

infra:
	./scripts/install_monitoring.sh

images:
	./scripts/build_images.sh

apps:
	./scripts/deploy_apps.sh

status:
	kubectl -n monitoring get pods,svc,servicemonitor,prometheusrule
	kubectl -n monitoring get configmap -l grafana_dashboard=1
	kubectl -n mlops-demo get pods,svc,pvc,job

ports:
	./scripts/port_forward.sh start

ports-status:
	./scripts/port_forward.sh status

ports-stop:
	./scripts/port_forward.sh stop

kube-ui:
	minikube dashboard

reset:
	./scripts/reset_demo.sh

check:
	uv run --group dev python tests/static_check.py
	uv run --group dev python tests/integration_static_check.py
	uv run --group dev pytest -q

evaluate:
	uv run --group dev python scripts/evaluate_model.py

data:
	uv run --group dev python data/generate_dataset.py

destroy:
	-kubectl delete namespace mlops-demo
	-helm uninstall monitoring -n monitoring
	-kubectl delete namespace monitoring
