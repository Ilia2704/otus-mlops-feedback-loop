.PHONY: up infra images apps status ports reset check evaluate data destroy

up: infra images apps

infra:
	./scripts/install_monitoring.sh

images:
	./scripts/build_images.sh

apps:
	./scripts/deploy_apps.sh

status:
	kubectl -n monitoring get pods
	kubectl -n mlops-demo get pods,svc,servicemonitor,prometheusrule

ports:
	./scripts/port_forward.sh

reset:
	./scripts/reset_demo.sh

check:
	python tests/static_check.py
	python tests/integration_static_check.py
	pytest -q

evaluate:
	python scripts/evaluate_model.py

data:
	python data/generate_dataset.py

destroy:
	-kubectl delete namespace mlops-demo
	-helm uninstall monitoring -n monitoring
	-kubectl delete namespace monitoring
