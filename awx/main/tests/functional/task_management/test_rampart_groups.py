import pytest
import mock
from datetime import timedelta
from awx.main.scheduler import TaskManager


@pytest.mark.django_db
def test_multi_group_basic_job_launch(instance_factory, default_instance_group, mocker,
                                      instance_group_factory, job_template_factory):
    i1 = instance_factory("i1")
    i2 = instance_factory("i2")
    ig1 = instance_group_factory("ig1", instances=[i1])
    ig2 = instance_group_factory("ig2", instances=[i2])
    objects1 = job_template_factory('jt1', organization='org1', project='proj1',
                                    inventory='inv1', credential='cred1',
                                    jobs=["job_should_start"])
    objects1.job_template.instance_groups.add(ig1)
    j1 = objects1.jobs['job_should_start']
    j1.status = 'pending'
    j1.save()
    objects2 = job_template_factory('jt2', organization='org2', project='proj2',
                                    inventory='inv2', credential='cred2',
                                    jobs=["job_should_still_start"])
    objects2.job_template.instance_groups.add(ig2)
    j2 = objects2.jobs['job_should_still_start']
    j2.status = 'pending'
    j2.save()
    with mock.patch('awx.main.models.Job.task_impact', new_callable=mock.PropertyMock) as mock_task_impact:
        mock_task_impact.return_value = 500
        with mocker.patch("awx.main.scheduler.TaskManager.start_task"):
            TaskManager().schedule()
            TaskManager.start_task.assert_has_calls([mock.call(j1, ig1, []), mock.call(j2, ig2, [])])



@pytest.mark.django_db
def test_multi_group_with_shared_dependency(instance_factory, default_instance_group, mocker,
                                            instance_group_factory, job_template_factory):
    i1 = instance_factory("i1")
    i2 = instance_factory("i2")
    ig1 = instance_group_factory("ig1", instances=[i1])
    ig2 = instance_group_factory("ig2", instances=[i2])
    objects1 = job_template_factory('jt1', organization='org1', project='proj1',
                                    inventory='inv1', credential='cred1',
                                    jobs=["job_should_start"])
    objects1.job_template.instance_groups.add(ig1)
    p = objects1.project
    p.scm_update_on_launch = True
    p.scm_update_cache_timeout = 0
    p.scm_type = "git"
    p.scm_url = "http://github.com/ansible/ansible.git"
    p.save()
    j1 = objects1.jobs['job_should_start']
    j1.status = 'pending'
    j1.save()
    objects2 = job_template_factory('jt2', organization=objects1.organization, project=p,
                                    inventory='inv2', credential='cred2',
                                    jobs=["job_should_still_start"])
    objects2.job_template.instance_groups.add(ig2)
    j2 = objects2.jobs['job_should_still_start']
    j2.status = 'pending'
    j2.save()
    with mocker.patch("awx.main.scheduler.TaskManager.start_task"):
        TaskManager().schedule()
        pu = p.project_updates.first()
        TaskManager.start_task.assert_called_once_with(pu, default_instance_group, [j1])
        pu.finished = pu.created + timedelta(seconds=1)
        pu.status = "successful"
        pu.save()
    with mock.patch("awx.main.scheduler.TaskManager.start_task"):
        TaskManager().schedule()

        TaskManager.start_task.assert_any_call(j1, ig1, [])
        TaskManager.start_task.assert_any_call(j2, ig2, [])
        assert TaskManager.start_task.call_count == 2


@pytest.mark.django_db
def test_overcapacity_blocking_other_groups_unaffected(instance_factory, default_instance_group, mocker,
                                                       instance_group_factory, job_template_factory):
    i1 = instance_factory("i1")
    i1.capacity = 1000
    i1.save()
    i2 = instance_factory("i2")
    ig1 = instance_group_factory("ig1", instances=[i1])
    ig2 = instance_group_factory("ig2", instances=[i2])
    objects1 = job_template_factory('jt1', organization='org1', project='proj1',
                                    inventory='inv1', credential='cred1',
                                    jobs=["job_should_start"])
    objects1.job_template.instance_groups.add(ig1)
    j1 = objects1.jobs['job_should_start']
    j1.status = 'pending'
    j1.save()
    objects2 = job_template_factory('jt2', organization=objects1.organization, project='proj2',
                                    inventory='inv2', credential='cred2',
                                    jobs=["job_should_start", "job_should_also_start"])
    objects2.job_template.instance_groups.add(ig1)
    j1_1 = objects2.jobs['job_should_also_start']
    j1_1.status = 'pending'
    j1_1.save()
    objects3 = job_template_factory('jt3', organization='org2', project='proj3',
                                    inventory='inv3', credential='cred3',
                                    jobs=["job_should_still_start"])
    objects3.job_template.instance_groups.add(ig2)
    j2 = objects3.jobs['job_should_still_start']
    j2.status = 'pending'
    j2.save()
    objects4 = job_template_factory('jt4', organization=objects3.organization, project='proj4',
                                    inventory='inv4', credential='cred4',
                                    jobs=["job_should_not_start"])
    objects4.job_template.instance_groups.add(ig2)
    j2_1 = objects4.jobs['job_should_not_start']
    j2_1.status = 'pending'
    j2_1.save()
    tm = TaskManager()
    with mock.patch('awx.main.models.Job.task_impact', new_callable=mock.PropertyMock) as mock_task_impact:
        mock_task_impact.return_value = 500
        with mock.patch.object(TaskManager, "start_task", wraps=tm.start_task) as mock_job:
            tm.schedule()
            mock_job.assert_has_calls([mock.call(j1, ig1, []), mock.call(j1_1, ig1, []),
                                       mock.call(j2, ig2, [])])
            assert mock_job.call_count == 3


@pytest.mark.django_db
def test_failover_group_run(instance_factory, default_instance_group, mocker,
                            instance_group_factory, job_template_factory):
    i1 = instance_factory("i1")
    i2 = instance_factory("i2")
    ig1 = instance_group_factory("ig1", instances=[i1])
    ig2 = instance_group_factory("ig2", instances=[i2])
    objects1 = job_template_factory('jt1', organization='org1', project='proj1',
                                    inventory='inv1', credential='cred1',
                                    jobs=["job_should_start"])
    objects1.job_template.instance_groups.add(ig1)
    j1 = objects1.jobs['job_should_start']
    j1.status = 'pending'
    j1.save()
    objects2 = job_template_factory('jt2', organization=objects1.organization, project='proj2',
                                    inventory='inv2', credential='cred2',
                                    jobs=["job_should_start", "job_should_also_start"])
    objects2.job_template.instance_groups.add(ig1)
    objects2.job_template.instance_groups.add(ig2)
    j1_1 = objects2.jobs['job_should_also_start']
    j1_1.status = 'pending'
    j1_1.save()
    tm = TaskManager()
    with mock.patch('awx.main.models.Job.task_impact', new_callable=mock.PropertyMock) as mock_task_impact:
        mock_task_impact.return_value = 500
        with mock.patch.object(TaskManager, "start_task", wraps=tm.start_task) as mock_job:
            tm.schedule()
            mock_job.assert_has_calls([mock.call(j1, ig1, []), mock.call(j1_1, ig2, [])])
            assert mock_job.call_count == 2
