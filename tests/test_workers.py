import unittest

from app.core.config import Settings
from app.core.contracts import ArchitecturePlan, WorkerSpec
from app.workers import WorkerDispatchError, WorkerDispatcher, WorkerFactory


def settings(**overrides):
    values = dict(
        gemini_api_key=None,
        gemini_model_architect="test-model",
        gemini_model_worker="test-worker",
        gemini_model_supervisor="test-supervisor",
        gemini_temperature=0.2,
        max_workers=4,
        min_workers=3,
        default_execution_timeout_seconds=60,
        max_uploads_per_message=20,
        max_upload_size_mb=100,
        execution_backend="colab",
        execution_gateway_url=None,
        execution_gateway_token=None,
    )
    values.update(overrides)
    return Settings(**values)


def worker(worker_id, dependencies=()):
    return WorkerSpec(
        worker_id=worker_id,
        role=f"role-{worker_id}",
        mission=f"mission-{worker_id}",
        deliverables=(f"{worker_id}-output",),
        dependencies=dependencies,
    )


class WorkerTests(unittest.TestCase):
    def test_factory_creates_run_scoped_workers(self):
        plan = ArchitecturePlan(
            plan_id="p",
            objective="x",
            workers=(worker("a"), worker("b", ("a",))),
        )
        workers = WorkerFactory(settings()).create_workers(run_id="run-1", plan=plan)
        self.assertEqual(tuple(item.worker_id for item in workers), ("a", "b"))
        self.assertTrue(all(item.run_id == "run-1" for item in workers))

    def test_dispatches_independent_workers_in_parallel_batch(self):
        workers = tuple(
            WorkerFactory(settings()).create_workers(
                run_id="run", plan=ArchitecturePlan(plan_id="p", objective="x", workers=(worker("a"), worker("b")))
            )
        )
        dispatcher = WorkerDispatcher(settings())
        batches = dispatcher.plan_batches(run_id="run", workers=workers)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].worker_ids(), ("a", "b"))

    def test_respects_dependency_order(self):
        factory = WorkerFactory(settings())
        plan = ArchitecturePlan(
            plan_id="p",
            objective="x",
            workers=(worker("a"), worker("b", ("a",)), worker("c", ("a",))),
        )
        workers = factory.create_workers(run_id="run", plan=plan)
        task = WorkerDispatcher.build_task(
            worker_id="b", description="build", expected_output="artifact", task_id="task-b"
        )
        batches = WorkerDispatcher(settings()).plan_batches(
            run_id="run", workers=workers, tasks=(task,)
        )
        self.assertEqual(batches[0].worker_ids(), ("a",))
        self.assertEqual(batches[1].worker_ids(), ("b", "c"))
        self.assertEqual(batches[1].tasks[0].task_id, "task-b")

    def test_rejects_cycle(self):
        workers = (
            WorkerFactory(settings()).create_workers(
                run_id="run",
                plan=ArchitecturePlan(
                    plan_id="p", objective="x", workers=(worker("a", ("b",)), worker("b", ("a",)))
                ),
            )
        )
        with self.assertRaises(WorkerDispatchError):
            WorkerDispatcher(settings()).plan_batches(run_id="run", workers=workers)

    def test_rejects_cross_run_worker(self):
        workers = WorkerFactory(settings()).create_workers(
            run_id="run-1", plan=ArchitecturePlan(plan_id="p", objective="x", workers=(worker("a"),))
        )
        with self.assertRaises(WorkerDispatchError):
            WorkerDispatcher(settings()).plan_batches(run_id="run-2", workers=workers)

    def test_rejects_unknown_task_worker(self):
        workers = WorkerFactory(settings()).create_workers(
            run_id="run", plan=ArchitecturePlan(plan_id="p", objective="x", workers=(worker("a"),))
        )
        task = WorkerDispatcher.build_task(
            worker_id="missing", description="x", expected_output="y", task_id="task"
        )
        with self.assertRaises(WorkerDispatchError):
            WorkerDispatcher(settings()).plan_batches(run_id="run", workers=workers, tasks=(task,))

    def test_enforces_worker_limit(self):
        plan = ArchitecturePlan(
            plan_id="p",
            objective="x",
            workers=tuple(worker(str(index)) for index in range(5)),
        )
        with self.assertRaises(Exception):
            WorkerFactory(settings(max_workers=4)).create_workers(run_id="run", plan=plan)


if __name__ == "__main__":
    unittest.main()
