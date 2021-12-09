import os
import unittest
import logging
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import SegmentEditorEffects
import functools

#
# LandmarkingView
#

class LandmarkingView(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "LandmarkingView"  # TODO: make this more human readable by adding spaces
    self.parent.categories = ["Examples"]  # TODO: set categories (folders where the module shows up in the module selector)
    self.parent.dependencies = []  # TODO: add here list of module names that this module requires
    self.parent.contributors = ["John Doe (AnyWare Corp.)"]  # TODO: replace with "Firstname Lastname (Organization)"
    # TODO: update with short description of the module and a link to online module documentation
    self.parent.helpText = """
    This is an example of scripted loadable module bundled in an extension.
    See more information in <a href="https://github.com/organization/projectname#LandmarkingView">module documentation</a>.
    """
    # TODO: replace with organization, grant and thanks
    self.parent.acknowledgementText = """
    This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
    and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
    """


#
# LandmarkingViewWidget
#

class LandmarkingViewWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent=None):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.__init__(self, parent)
    VTKObservationMixin.__init__(self)  # needed for parameter node observation
    self.logic = None
    self._parameterNode = None
    self._updatingGUIFromParameterNode = False

    self.__linkViews()

    self.compositeNode = None
    self.volumes_names = None

    # variable saying if views in 3-over-3 are linked or not
    self.linked = False
    self.view = 'normal'
    self.views_normal = ["Red", "Green", "Yellow"]
    self.views_plus = ["Red+", "Green+", "Yellow+"]

  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

    # Load widget from .ui file (created by Qt Designer).
    # Additional widgets can be instantiated manually and added to self.layout.
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/LandmarkingView.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
    # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
    # "setMRMLScene(vtkMRMLScene*)" slot.
    uiWidget.setMRMLScene(slicer.mrmlScene)

    # Create logic class. Logic implements all computations that should be possible to run
    # in batch mode, without a graphical user interface.
    self.logic = LandmarkingViewLogic()

    # Connections

    # These connections ensure that we update parameter node when scene is closed
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    # (in the selected parameter node).
    self.ui.inputSelector1.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
    self.ui.inputSelector2.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
    self.ui.inputSelector3.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)

    # Buttons
    # create intersection outline
    self.ui.intersectionButton.connect('clicked(bool)', self.onIntersectionButton)
    # set foreground threshold to 1 for all chosen volumes
    self.ui.thresholdButton.connect('clicked(bool)', self.onThresholdButton)
    # change to standard view
    self.ui.viewStandardButton.connect('clicked(bool)', self.onViewStandardButton)
    # change to 3 over 3 view view
    self.ui.view3o3Button.connect('clicked(bool)', self.onView3o3Button)

    # Check boxes
    # link top and bottom view
    self.ui.linkCheckBox.connect('toggled(bool)', self.onLinkCheckBox)
    # self.ui.linkCheckBox.connect('not toggled(bool)', self.onLinkCheckBox)

    # Make sure parameter node is initialized (needed for module reload)
    self.initializeParameterNode()

    # shortcuts
    self.__initialiseShortcuts()  # those that depend on the volumes - they have to be defined in this class,
    # as they need the updated ui stuff to work

  def cleanup(self):
    """
    Called when the application closes and the module widget is destroyed.
    """
    self.removeObservers()

  def enter(self):
    """
    Called each time the user opens this module.
    """
    # Make sure parameter node exists and observed
    self.initializeParameterNode()

  def exit(self):
    """
    Called each time the user opens a different module.
    """
    # Do not react to parameter node changes (GUI wlil be updated when the user enters into the module)
    self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

  def onSceneStartClose(self, caller, event):
    """
    Called just before the scene is closed.
    """
    # Parameter node will be reset, do not use it anymore
    self.setParameterNode(None)

  def onSceneEndClose(self, caller, event):
    """
    Called just after the scene is closed.
    """
    # If this module is shown while the scene is closed then recreate a new parameter node immediately
    if self.parent.isEntered:
      self.initializeParameterNode()

  def initializeParameterNode(self):
    """
    Ensure parameter node exists and observed.
    """
    # Parameter node stores all user choices in parameter values, node selections, etc.
    # so that when the scene is saved and reloaded, these settings are restored.

    self.setParameterNode(self.logic.getParameterNode())

    # Select default input nodes if nothing is selected yet to save a few clicks for the user
    for input_volume, volume_name in zip(["InputVolume1", "InputVolume2", "InputVolume3"],
                                         ["US1 Pre-dura", "US2 Post-dura", "US3 Resection Control"]):
      if not self._parameterNode.GetNodeReference(input_volume):
        volumeNode = slicer.mrmlScene.GetFirstNodeByName(volume_name)
        if volumeNode:
          self._parameterNode.SetNodeReferenceID(input_volume, volumeNode.GetID())

  def setParameterNode(self, inputParameterNode):
    """
    Set and observe parameter node.
    Observation is needed because when the parameter node is changed then the GUI must be updated immediately.
    """

    # Unobserve previously selected parameter node and add an observer to the newly selected.
    # Changes of parameter node are observed so that whenever parameters are changed by a script or any other module
    # those are reflected immediately in the GUI.
    if self._parameterNode is not None:
      self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    self._parameterNode = inputParameterNode
    if self._parameterNode is not None:
      self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    # Initial GUI update
    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self, caller=None, event=None):
    """
    This method is called whenever parameter node is changed.
    The module GUI is updated to show the current state of the parameter node.
    """

    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    # Make sure GUI changes do not call updateParameterNodeFromGUI (it could cause infinite loop)
    self._updatingGUIFromParameterNode = True

    # Update node selectors and sliders
    self.ui.inputSelector1.setCurrentNode(self._parameterNode.GetNodeReference("InputVolume1"))
    self.ui.inputSelector2.setCurrentNode(self._parameterNode.GetNodeReference("InputVolume2"))
    self.ui.inputSelector3.setCurrentNode(self._parameterNode.GetNodeReference("InputVolume3"))

    # update button states and tooltips - only if volumes are chosen, enable buttons
    if self._parameterNode.GetNodeReference("InputVolume1") and \
       self._parameterNode.GetNodeReference("InputVolume2") and \
       self._parameterNode.GetNodeReference("InputVolume3"):
      self.ui.intersectionButton.toolTip = "Compute intersection"
      self.ui.intersectionButton.enabled = True

      self.ui.thresholdButton.toolTip = "Set lower thresholds of chosen volumes to 1"
      self.ui.thresholdButton.enabled = True
    else:
      self.ui.intersectionButton.toolTip = "Select all input volumes first"
      self.ui.intersectionButton.enabled = False

      self.ui.thresholdButton.toolTip = "Select all input volumes first"
      self.ui.thresholdButton.enabled = False

    # All the GUI updates are done
    self._updatingGUIFromParameterNode = False

  def updateParameterNodeFromGUI(self, caller=None, event=None):
    """
    This method is called when the user makes any change in the GUI.
    The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
    """

    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

    self._parameterNode.SetNodeReferenceID("InputVolume1", self.ui.inputSelector1.currentNodeID)
    self._parameterNode.SetNodeReferenceID("InputVolume2", self.ui.inputSelector2.currentNodeID)
    self._parameterNode.SetNodeReferenceID("InputVolume3", self.ui.inputSelector3.currentNodeID)

    self._parameterNode.EndModify(wasModified)

  def __initialise_views(self):
    """
    Initialise views with the US volumes
    :return the composite node that can be used by the change view function
    """

    self.volumes_names = [self.ui.inputSelector1.currentNode().GetName(),
                          self.ui.inputSelector2.currentNode().GetName(),
                          self.ui.inputSelector3.currentNode().GetName()]

    # get current foreground and background volumes
    if self.linked and self.view == '3on3':  # if it is linked and 3on3, we want it to change in all slices
      current_views = self.views_normal + self.views_plus
    else:
      current_views = self.views_normal

    for view in current_views:

      layoutManager = slicer.app.layoutManager()
      view_logic = layoutManager.sliceWidget(view).sliceLogic()
      self.compositeNode = view_logic.GetSliceCompositeNode()

      current_background_id = self.compositeNode.GetBackgroundVolumeID()
      current_foreground_id = self.compositeNode.GetForegroundVolumeID()

      # check if there is a background
      if current_background_id is not None:
        current_background_volume = slicer.mrmlScene.GetNodeByID(current_background_id)
        current_background_name = current_background_volume.GetName()

        # if it's not the correct volume, set the background and foreground
        if current_background_name not in self.volumes_names:
          volume_background = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[2])
          volume_foreground = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[1])

          # update volumes
          self.compositeNode.SetBackgroundVolumeID(volume_background.GetID())
          self.compositeNode.SetForegroundVolumeID(volume_foreground.GetID())

      else:  # there is no background
        volume_background = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[2])
        volume_foreground = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[1])

        # update volumes
        self.compositeNode.SetBackgroundVolumeID(volume_background.GetID())
        self.compositeNode.SetForegroundVolumeID(volume_foreground.GetID())

      # check if there is a foreground
      if current_foreground_id is not None:
        current_foreground_volume = slicer.mrmlScene.GetNodeByID(current_background_id)
        current_foreground_name = current_foreground_volume.GetName()

        # if it's not the correct volume, set the background and foreground
        if current_foreground_name not in self.volumes_names:
          volume_background = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[2])
          volume_foreground = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[1])
          # update volumes
          self.compositeNode.SetBackgroundVolumeID(volume_background.GetID())
          self.compositeNode.SetForegroundVolumeID(volume_foreground.GetID())

      else:  # there is no foreground
        volume_background = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[2])
        volume_foreground = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[1])

        # update volumes
        self.compositeNode.SetBackgroundVolumeID(volume_background.GetID())
        self.compositeNode.SetForegroundVolumeID(volume_foreground.GetID())

  def __change_view(self, direction='forward'):
    """
    Change the view forward or backward (take the list three possible volumes and for the two displayed volumes increase
    their index by one)
    :param direction:
    :return:
    """
    # TODO try to simplify code, seems very complex

    if self.ui.inputSelector1.currentNode() is None or\
       self.ui.inputSelector2.currentNode() is None or\
       self.ui.inputSelector3.currentNode() is None:
      slicer.util.errorDisplay("Not enough volumes given for the volume switching shortcut (choose all in the 'Common "
                               "field of view'")
      return

    self.__initialise_views()

    #print(self.linked)

    if self.linked and self.view == '3on3':  # if it is linked, we want it to change in all slices
      current_views = self.views_normal + self.views_plus
    else:
      current_views = self.views_normal

    for view in current_views:

      layoutManager = slicer.app.layoutManager()
      view_logic = layoutManager.sliceWidget(view)
      view_logic = view_logic.sliceLogic()
      self.compositeNode = view_logic.GetSliceCompositeNode()

      volume_background = None
      volume_foreground = None

      # get current foreground and background volumes
      current_foreground_id = self.compositeNode.GetForegroundVolumeID()
      current_foreground_volume = slicer.mrmlScene.GetNodeByID(current_foreground_id)
      current_foreground_name = current_foreground_volume.GetName()
      current_background_id = self.compositeNode.GetBackgroundVolumeID()
      current_background_volume = slicer.mrmlScene.GetNodeByID(current_background_id)
      current_background_name = current_background_volume.GetName()

      # switch backgrounds
      if direction == 'forward':
        if current_background_name == self.volumes_names[2] and current_foreground_name == self.volumes_names[1]:
          volume_background = current_foreground_volume
          volume_foreground = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[0])
        elif current_background_name == self.volumes_names[1] and current_foreground_name == self.volumes_names[0]:
          volume_background = current_foreground_volume
          volume_foreground = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[2])
        elif current_background_name == self.volumes_names[0] and current_foreground_name == self.volumes_names[2]:
          volume_background = current_foreground_volume
          volume_foreground = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[1])
        elif current_background_name == self.volumes_names[2] and current_foreground_name == self.volumes_names[0]:
          volume_foreground = current_background_volume
          volume_background = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[1])
        elif current_background_name == self.volumes_names[0] and current_foreground_name == self.volumes_names[1]:
          volume_foreground = current_background_volume
          volume_background = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[2])
        elif current_background_name == self.volumes_names[1] and current_foreground_name == self.volumes_names[2]:
          volume_foreground = current_background_volume
          volume_background = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[0])

      elif direction == 'backward':
        if current_background_name == self.volumes_names[2] and current_foreground_name == self.volumes_names[1]:
          volume_foreground = current_background_volume
          volume_background = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[0])
        elif current_background_name == self.volumes_names[1] and current_foreground_name == self.volumes_names[0]:
          volume_foreground = current_background_volume
          volume_background = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[2])
        elif current_background_name == self.volumes_names[0] and current_foreground_name == self.volumes_names[2]:
          volume_foreground = current_background_volume
          volume_background = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[1])
        elif current_background_name == self.volumes_names[2] and current_foreground_name == self.volumes_names[0]:
          volume_background = current_foreground_volume
          volume_foreground = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[1])
        elif current_background_name == self.volumes_names[0] and current_foreground_name == self.volumes_names[1]:
          volume_background = current_foreground_volume
          volume_foreground = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[2])
        elif current_background_name == self.volumes_names[1] and current_foreground_name == self.volumes_names[2]:
          volume_background = current_foreground_volume
          volume_foreground = slicer.mrmlScene.GetFirstNodeByName(self.volumes_names[0])

      # update volumes (if they both exist)
      if volume_foreground and volume_background:
        if direction == 'backward' or direction == 'forward':
          self.compositeNode.SetBackgroundVolumeID(volume_background.GetID())
          self.compositeNode.SetForegroundVolumeID(volume_foreground.GetID())
          # slicer.util.setSliceViewerLayers(background=volume_background, foreground=volume_foreground)
        else:
          print("wrong direction")
      else:
        print("No volumes to set for foreground and background")

  def __createFiducialPlacer(self):
    """
    Switch to the fiducial placer tool
    """
    self.interactionNode = slicer.app.applicationLogic().GetInteractionNode()

  def __change_foreground_opacity_discrete(self, new_opacity=0.5):
    layoutManager = slicer.app.layoutManager()

    # iterate through all views and set opacity to
    for sliceViewName in layoutManager.sliceViewNames():
      view = layoutManager.sliceWidget(sliceViewName).sliceView()
      sliceNode = view.mrmlSliceNode()
      sliceLogic = slicer.app.applicationLogic().GetSliceLogic(sliceNode)
      compositeNode = sliceLogic.GetSliceCompositeNode()
      compositeNode.SetForegroundOpacity(new_opacity)

  def __change_foreground_opacity_continuous(self, opacity_change=0.01):
    # TODO threshold change needs to be initialized once with setting it to 0.5 with discrete, otherwise it's stuck
    layoutManager = slicer.app.layoutManager()

    # iterate through all views and set opacity to
    for sliceViewName in layoutManager.sliceViewNames():
      view = layoutManager.sliceWidget(sliceViewName).sliceView()
      sliceNode = view.mrmlSliceNode()
      sliceLogic = slicer.app.applicationLogic().GetSliceLogic(sliceNode)
      compositeNode = sliceLogic.GetSliceCompositeNode()
      compositeNode.SetForegroundOpacity(compositeNode.GetForegroundOpacity() + opacity_change)

  def __set_foreground_threshold(self, threshold):
    """
    Set foreground threshold to 1, so that the surrounding black pixels disappear
    """
    # get current foreground
    layoutManager = slicer.app.layoutManager()
    view = layoutManager.sliceWidget('Red').sliceView()
    sliceNode = view.mrmlSliceNode()
    sliceLogic = slicer.app.applicationLogic().GetSliceLogic(sliceNode)
    compositeNode = sliceLogic.GetSliceCompositeNode()

    current_foreground_id = compositeNode.GetForegroundVolumeID()
    current_foreground_volume = slicer.mrmlScene.GetNodeByID(current_foreground_id)
    current_foreground_name = current_foreground_volume.GetName()

    volNode = slicer.util.getNode(current_foreground_name)
    dispNode = volNode.GetDisplayNode()
    dispNode.ApplyThresholdOn()
    dispNode.SetLowerThreshold(threshold)  # 1 because we want to surrounding black pixels to disappear
    #current_foreground_volume.AddObserver(slicer.vtkMRMLScalarVolumeDisplayNode.PointModifiedEvent, dispNode.SetLowerThreshold)

  def __create_shortcuts(self):

    self.__createFiducialPlacer()

    self.shortcuts = [('d', lambda: self.interactionNode.SetCurrentInteractionMode(self.interactionNode.Place)),
                      # fiducial placement
                      ('a', functools.partial(self.__change_view, "backward")),  # volume switching dir1
                      ('s', functools.partial(self.__change_view, "forward")),  # volume switching dir2
                      ('1', functools.partial(self.__change_foreground_opacity_discrete, 0.0)),  # change opacity to 0.5
                      ('2', functools.partial(self.__change_foreground_opacity_discrete, 0.5)),  # change opacity to 0.5
                      ('3', functools.partial(self.__change_foreground_opacity_discrete, 1.0)),  # change opacity to 1.0
                      ('q', functools.partial(self.__change_foreground_opacity_continuous, 0.02)),  # incr. op. by .01
                      ('w', functools.partial(self.__change_foreground_opacity_continuous, -0.02)),  # decr. op. by .01
                      ('l', functools.partial(self.__set_foreground_threshold, 1))]  # set foreground threshold to 1

  def __initialiseShortcuts(self):

    self.__create_shortcuts()

    for (shortcutKey, callback) in self.shortcuts:
      shortcut = qt.QShortcut(slicer.util.mainWindow())
      shortcut.setKey(qt.QKeySequence(shortcutKey))
      shortcut.connect('activated()', callback)

  def __linkViews(self):
    """
    # link views
    # Set linked slice views  in all existing slice composite nodes and in the default node
    """

    sliceCompositeNodes = slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode")
    defaultSliceCompositeNode = slicer.mrmlScene.GetDefaultNodeByClass("vtkMRMLSliceCompositeNode")
    if not defaultSliceCompositeNode:
      defaultSliceCompositeNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLSliceCompositeNode")
      defaultSliceCompositeNode.UnRegister(
        None)  # CreateNodeByClass is factory method, need to unregister the result to prevent memory leaks
      slicer.mrmlScene.AddDefaultNode(defaultSliceCompositeNode)
    sliceCompositeNodes.append(defaultSliceCompositeNode)
    for sliceCompositeNode in sliceCompositeNodes:
      sliceCompositeNode.SetLinkedControl(True)

  def onIntersectionButton(self):
    """
    Run processing when user clicks "Create intersection" button.
    """
    try:
      # Compute output
      self.logic.process(self.ui.inputSelector1.currentNode(),
                         self.ui.inputSelector2.currentNode(),
                         self.ui.inputSelector3.currentNode())

      self.__initialise_views()

    except:
      pass

  def onThresholdButton(self):
    try:
      threshold = 1

      # loop through all selected volumes
      for volume in [self.ui.inputSelector1.currentNode(),
                     self.ui.inputSelector2.currentNode(),
                     self.ui.inputSelector3.currentNode()]:

        current_name = volume.GetName()

        volNode = slicer.util.getNode(current_name)
        dispNode = volNode.GetDisplayNode()
        dispNode.ApplyThresholdOn()
        dispNode.SetLowerThreshold(threshold)  # 1 because we want to surrounding black pixels to disappear

    except Exception as e:
      slicer.util.errorDisplay("Failed to change lower thresholds. " + str(e))

  def onViewStandardButton(self):
    try:
      slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)

      # set slice orientation
      sliceNodes = slicer.util.getNodesByClass("vtkMRMLSliceNode")
      sliceNodes[0].SetOrientationToAxial()
      sliceNodes[1].SetOrientationToCoronal()
      sliceNodes[2].SetOrientationToSagittal()

      self.ui.linkCheckBox.toolTip = "Switch to 3-over-3 view to enable linking of top and bottom row"
      self.ui.linkCheckBox.enabled = False

      self.view = 'normal'

    except Exception as e:
      slicer.util.errorDisplay("Failed to change to standard view. " + str(e))

  def onView3o3Button(self):
    try:
      slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutThreeOverThreeView)

      # set slice orientation
      sliceNodes = slicer.util.getNodesByClass("vtkMRMLSliceNode")
      sliceNodes[0].SetOrientationToAxial()
      sliceNodes[1].SetOrientationToCoronal()
      sliceNodes[2].SetOrientationToSagittal()
      sliceNodes[3].SetOrientationToAxial()
      sliceNodes[4].SetOrientationToCoronal()
      sliceNodes[5].SetOrientationToSagittal()

      self.__initialise_views()

      self.ui.linkCheckBox.toolTip = "Enable linking of top and bottom row"
      self.ui.linkCheckBox.enabled = True

      self.view = '3on3'

    except Exception as e:
      slicer.util.errorDisplay("Failed to change to 3 over 3 view. " + str(e))

  def onLinkCheckBox(self, link=False):
    try:
      self.linked = link

      if link:
        group_normal = group_plus = 0
      else:
        group_normal = 0
        group_plus = 1

      # set groups
      for i in range(3):
        slicer.app.layoutManager().sliceWidget(self.views_normal[i]).mrmlSliceNode().SetViewGroup(group_normal)
        slicer.app.layoutManager().sliceWidget(self.views_plus[i]).mrmlSliceNode().SetViewGroup(group_plus)

    except Exception as e:
      slicer.util.errorDisplay("Failed link (or unlink) views. " + str(e))


#
# LandmarkingViewLogic
#

class LandmarkingViewLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self):
    """
    Called when the logic class is instantiated. Can be used for initializing member variables.
    """
    ScriptedLoadableModuleLogic.__init__(self)

  @staticmethod
  def setup_segment_editor(segment_name, segmentationNode=None, volumeNode=None):
    """
    Runs standard setup of segment editor widget and segment editor node
    :param segmentationNode a seg node you can also pass
    :param volumeNode a volume node you can pass
    """

    if segmentationNode is None:
      # Create segmentation node
      segmentationNode = slicer.vtkMRMLSegmentationNode()
      slicer.mrmlScene.AddNode(segmentationNode)
      segmentationNode.CreateDefaultDisplayNodes()
      segmentationNode.SetName(segment_name)

    segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
    segmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
    segmentEditorNode.SetOverwriteMode(slicer.vtkMRMLSegmentEditorNode.OverwriteNone)
    slicer.mrmlScene.AddNode(segmentEditorNode)
    segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
    segmentEditorWidget.setSegmentationNode(segmentationNode)
    segmentEditorWidget.setMRMLScene(slicer.mrmlScene)

    if volumeNode:
      segmentEditorWidget.setMasterVolumeNode(volumeNode)

    return segmentEditorWidget, segmentEditorNode, segmentationNode

  def process(self, volume1, volume2, volume3):
    """
    Creates the intersectin of the first three volumes and siplays it as an outline
    """

    if volume1 is None or volume2 is None or volume3 is None:
      slicer.util.errorDisplay( "Select all three volumes")
      return

    import time
    startTime = time.time()
    logging.info('Processing started')

    # usVolumes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
    usVolumes = (volume1, volume2, volume3)

    # initialise segment editor
    segmentEditorWidget, segmentEditorNode, segmentationNode = self.setup_segment_editor("us_outlines")

    addedSegmentID = []

    # for each volume create a threshold segmentation
    for idx, volume in enumerate(usVolumes):
      segmentEditorWidget.setMasterVolumeNode(volume)

      # Create segment
      addedSegmentID.append(segmentationNode.GetSegmentation().AddEmptySegment(volume.GetName()[0:3] + "_bb"))
      segmentEditorNode.SetSelectedSegmentID(addedSegmentID[idx])

      # Fill by thresholding
      segmentEditorWidget.setActiveEffectByName("Threshold")
      effect = segmentEditorWidget.activeEffect()
      effect.setParameter("MinimumThreshold", "1")
      effect.setParameter("MaximumThreshold", "255")
      effect.self().onApply()

    # https://slicer.readthedocs.io/en/latest/developer_guide/modules/segmenteditor.html#effect-parameters
    # https://discourse.slicer.org/t/how-to-programmatically-use-logical-operator-add-function-from-segment-editor/16581/2
    # https://discourse.slicer.org/t/how-to-change-the-slice-fill-in-segmentations-in-a-python-script/20871/2
    # Display settings are stored in the display node
    intersection_segment_id = segmentationNode.GetSegmentation().AddEmptySegment("intersection")
    segmentEditorNode.SetSelectedSegmentID(intersection_segment_id)
    segmentEditorWidget.setActiveEffectByName("Logical operators")
    effect = segmentEditorWidget.activeEffect()

    # add first segmentations
    effect.setParameter("Operation", SegmentEditorEffects.LOGICAL_UNION)

    effect.setParameter("ModifierSegmentID", volume1.GetName()[0:3] + "_bb")
    effect.self().onApply()

    # intersect with the next two segmentations
    effect.setParameter("Operation", SegmentEditorEffects.LOGICAL_INTERSECT)

    effect.setParameter("ModifierSegmentID", volume2.GetName()[0:3] + "_bb")
    effect.self().onApply()

    effect.setParameter("ModifierSegmentID", volume3.GetName()[0:3] + "_bb")
    effect.self().onApply()

    # remove segments
    for id in addedSegmentID:
      if "intersection" not in id:
        segmentationNode.RemoveSegment(id)

    # display only outline
    # https://slicer.readthedocs.io/en/latest/developer_guide/script_repository.html#modify-segmentation-display-options
    # http://apidocs.slicer.org/master/classvtkMRMLSegmentationDisplayNode.html#afeca62a2a79513ab275db3840136709c
    segmentation = slicer.mrmlScene.GetFirstNodeByName('us_outlines')
    displayNode = segmentation.GetDisplayNode()
    displayNode.SetSegmentOpacity2DFill(intersection_segment_id, 0.0)  # Set fill opacity of a single segment
    displayNode.SetSegmentOpacity2DOutline(intersection_segment_id, 1.0)  # Set outline opacity of a single segment

    stopTime = time.time()
    logging.info('Processing completed in {0:.2f} seconds'.format(stopTime-startTime))

#
# LandmarkingViewTest
#

class LandmarkingViewTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear()

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_LandmarkingView1()

  def test_LandmarkingView1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    self.delayDisplay("Starting the test")

    # Get/create input data

    import SampleData
    registerSampleData()
    inputVolume = SampleData.downloadSample('LandmarkingView1')
    self.delayDisplay('Loaded test data set')

    inputScalarRange = inputVolume.GetImageData().GetScalarRange()
    self.assertEqual(inputScalarRange[0], 0)
    self.assertEqual(inputScalarRange[1], 695)

    outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
    threshold = 100

    # Test the module logic

    logic = LandmarkingViewLogic()

    # Test algorithm with non-inverted threshold
    logic.process(inputVolume, outputVolume, threshold, True)
    outputScalarRange = outputVolume.GetImageData().GetScalarRange()
    self.assertEqual(outputScalarRange[0], inputScalarRange[0])
    self.assertEqual(outputScalarRange[1], threshold)

    # Test algorithm with inverted threshold
    logic.process(inputVolume, outputVolume, threshold, False)
    outputScalarRange = outputVolume.GetImageData().GetScalarRange()
    self.assertEqual(outputScalarRange[0], inputScalarRange[0])
    self.assertEqual(outputScalarRange[1], inputScalarRange[1])

    self.delayDisplay('Test passed')
