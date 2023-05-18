from leapp.actors import Actor
from leapp.libraries.actor import modscan
from leapp.tags import FactsPhaseTag, IPUWorkflowTag

from leapp.models import (  # isort:skip
    TargetUserSpaceUpgradeTasks,
    UpgradeInitramfsTasks
)


class TestAddKernelModule(Actor):
    """
    Add kernel modules
    """

    name = 'test_add_kernel_module'
    consumes = ()
    produces = (
        TargetUserSpaceUpgradeTasks,
        UpgradeInitramfsTasks,
    )
    tags = (IPUWorkflowTag, FactsPhaseTag)

    def process(self):
        modscan.process()
