#!/usr/bin/env python

# Import modules
import numpy as np
import sklearn
from sklearn.preprocessing import LabelEncoder
import pickle
from sensor_stick.srv import GetNormals
from sensor_stick.features import compute_color_histograms
from sensor_stick.features import compute_normal_histograms
from visualization_msgs.msg import Marker
from sensor_stick.marker_tools import *
from sensor_stick.msg import DetectedObjectsArray
from sensor_stick.msg import DetectedObject
from sensor_stick.pcl_helper import *

import rospy
import tf
from geometry_msgs.msg import Pose
from std_msgs.msg import Float64
from std_msgs.msg import Int32
from std_msgs.msg import String
from pr2_robot.srv import *
from rospy_message_converter import message_converter
import yaml
import math


# Helper function to get surface normals
def get_normals(cloud):
    get_normals_prox = rospy.ServiceProxy('/feature_extractor/get_normals', GetNormals)
    return get_normals_prox(cloud).cluster

# Helper function to create a yaml friendly dictionary from ROS messages
def make_yaml_dict(test_scene_num, arm_name, object_name, pick_pose, place_pose):
    yaml_dict = {}
    yaml_dict["test_scene_num"] = test_scene_num.data
    yaml_dict["arm_name"]  = arm_name.data
    yaml_dict["object_name"] = object_name.data
    yaml_dict["pick_pose"] = message_converter.convert_ros_message_to_dictionary(pick_pose)
    yaml_dict["place_pose"] = message_converter.convert_ros_message_to_dictionary(place_pose)
    return yaml_dict

# Helper function to output to yaml file
def send_to_yaml(yaml_filename, dict_list):
    data_dict = {"object_list": dict_list}
    with open(yaml_filename, 'w') as outfile:
        yaml.dump(data_dict, outfile, default_flow_style=False)

# To merge two point cloud_objects
def merge_cloud(cloud1, cloud2):
    merged_cloud_list = []
    for point in cloud1:
        merged_cloud_list.append(point)

    for point in cloud2:
        merged_cloud_list.append(point)

    merged_cloud = pcl.PointCloud_PointXYZRGB()
    merged_cloud.from_list(merged_cloud_list)
    return merged_cloud

# Callback function for your Point Cloud Subscriber
def pcl_callback(pcl_msg):

# Exercise-2 TODOs:

    # Convert ROS msg to PCL data
    cloud = ros_to_pcl(pcl_msg)

    # Voxel Grid Downsampling
    vox = cloud.make_voxel_grid_filter()
    LEAF_SIZE = 0.01
    vox.set_leaf_size(LEAF_SIZE, LEAF_SIZE, LEAF_SIZE)
    cloud_filtered = vox.filter()

    # PassThrough Filter
    # Z direction
    passthrough_1 = cloud_filtered.make_passthrough_filter()
    filter_axis_1 = 'z'
    passthrough_1.set_filter_field_name(filter_axis_1)
    axis_1_min = 0.6
    axis_1_max = 1.2
    passthrough_1.set_filter_limits(axis_1_min, axis_1_max)
    cloud_filtered = passthrough_1.filter()

    # Y direction
    passthrough_2 = cloud_filtered.make_passthrough_filter()
    filter_axis_2 = 'y'
    passthrough_2.set_filter_field_name(filter_axis_2)
    axis_2_min = -0.5
    axis_2_max = 0.5
    passthrough_2.set_filter_limits(axis_2_min, axis_2_max)
    cloud_filtered = passthrough_2.filter()

    # X direction
    passthrough_3 = cloud_filtered.make_passthrough_filter()
    filter_axis_3 = 'x'
    passthrough_3.set_filter_field_name(filter_axis_3)
    axis_3_min = 0.3
    axis_3_max = 1.1
    passthrough_3.set_filter_limits(axis_3_min, axis_3_max)
    cloud_filtered = passthrough_3.filter()

    # Add Outlier Removal Filter
    outlier_filter = cloud_filtered.make_statistical_outlier_filter()
    outlier_filter.set_mean_k(50)
    x = 0.2
    outlier_filter.set_std_dev_mul_thresh(x)
    cloud_filtered = outlier_filter.filter()

    # RANSAC Plane Segmentation
    seg = cloud_filtered.make_segmenter()
    seg.set_model_type(pcl.SACMODEL_PLANE)
    seg.set_method_type(pcl.SAC_RANSAC)
    max_distance = 0.01
    seg.set_distance_threshold(max_distance)

    # Extract inliers and outliers
    inliers, cofficients = seg.segment()
    cloud_table = cloud_filtered.extract(inliers, negative=False)
    cloud_objects = cloud_filtered.extract(inliers, negative=True)

    # Euclidean Clustering
    white_cloud = XYZRGB_to_XYZ(cloud_objects)# Apply function to convert XYZRGB to XYZ
    tree = white_cloud.make_kdtree()

    # Create Cluster-Mask Point Cloud to visualize each cluster separately
    # Create a cluster extraction object
    ec = white_cloud.make_EuclideanClusterExtraction()
    ec.set_ClusterTolerance(0.05)
    ec.set_MinClusterSize(10)
    ec.set_MaxClusterSize(1000)
    # Search the k-d tree for clusters
    ec.set_SearchMethod(tree)
    # Extract indices for each of the discovered clusters
    cluster_indices = ec.Extract()
    #Assign a color corresponding to each segmented object in scene
    cluster_color = get_color_list(len(cluster_indices))

    color_cluster_point_list = []

    for j, indices in enumerate(cluster_indices):
        for i, indice in enumerate(indices):
            color_cluster_point_list.append([white_cloud[indice][0],
                                            white_cloud[indice][1],
                                            white_cloud[indice][2],
                                            rgb_to_float(cluster_color[j])])

    #Create new cloud containing all clusters, each with unique color
    cluster_cloud = pcl.PointCloud_PointXYZRGB()
    cluster_cloud.from_list(color_cluster_point_list)

    # Convert PCL data to ROS messages
    ros_cloud_objects = pcl_to_ros(cloud_objects)
    ros_cloud_table = pcl_to_ros(cloud_table)
    ros_cluster_cloud = pcl_to_ros(cluster_cloud)

    # Prepare obstacle point cloud if just consider the table and all object as obstacles
    # obstacle_cloud = merge_cloud(cloud_table, cloud_objects)
    # ros_cloud_obstacle = pcl_to_ros(obstacle_cloud)

    # Publish ROS messages
    pcl_objects_pub.publish(ros_cloud_objects)
    pcl_table_pub.publish(ros_cloud_table)
    pcl_cluster_pub.publish(ros_cluster_cloud)
    # pcl_obstacle_pub.publish(ros_cloud_obstacle)

# Exercise-3 TODOs:

    # Classify the clusters! (loop through each detected cluster one at a time)v
    detected_objects_labels = []
    detected_objects = []

    for index, pts_list in enumerate(cluster_indices):
        # Grab the points for the cluster
        pcl_cluster = cloud_objects.extract(pts_list)
        ros_cluster = pcl_to_ros(pcl_cluster)

        # Compute the associated feature vector
        chists = compute_color_histograms(ros_cluster, using_hsv=True)
        normals = get_normals(ros_cluster)
        nhists = compute_normal_histograms(normals)
        feature = np.concatenate((chists, nhists))

        # Make the prediction, retrieve the label for the result
        # and add it to detected_objects_labels list
        prediction = clf.predict(scaler.transform(feature.reshape(1,-1)))
        label = encoder.inverse_transform(prediction)[0]
        detected_objects_labels.append(label)

        # Publish a label into RViz
        label_pos = list(white_cloud[pts_list[0]])
        label_pos[2] += .4
        object_markers_pub.publish(make_label(label,label_pos, index))

        # Add the detected object to the list of detected objects.
        do = DetectedObject()
        do.label = label
        do.cloud = ros_cluster
        detected_objects.append(do)

    rospy.loginfo('Detected {} objects: {}'.format(len(detected_objects_labels), detected_objects_labels))

    # Publish the list of detected objects
    # This is the output you'll need to complete the upcoming project!
    detected_objects_pub.publish(detected_objects)

    # Suggested location for where to invoke your pr2_mover() function within pcl_callback()
    # Could add some logic to determine whether or not your object detections are robust
    # before calling pr2_mover()
    try:
        pr2_mover(detected_objects, cloud_table) # detected_objects_list
    except rospy.ROSInterruptException:
        pass

# function to load parameters and request PickPlace service
def pr2_mover(object_list, cloud_table):

    # Initialize variables
    test_scene_num = Int32()
    object_name = String()
    arm_name = String()
    pick_pose = Pose()
    place_pose = Pose()

    dict_list = []
    yaml_filename = 'output_1.yaml'
    test_scene_num.data = 1

    ## Get data from detected_object_list
    labels = []
    centroids = [] # to be list of tuples (x, y, z)
    for object in object_list:
        labels.append(object.label)
        points_arr = ros_to_pcl(object.cloud).to_array()
        centroids.append(np.mean(points_arr, axis=0)[:3])

    # Get/Read parameters
    object_list_param = rospy.get_param('/object_list')
    dropbox_param = rospy.get_param('/dropbox')

    # TODO: Parse parameters into individual variables
    # NO need


    # # TODO: Rotate PR2 in place to capture side tables for the collision map
    world_joint_pub.publish(-90 * math.pi / 180)
    rospy.sleep(abs(16.0))
    world_joint_pub.publish(90 * math.pi / 180)
    rospy.sleep(abs(16.0))
    world_joint_pub.publish(0 * math.pi / 180)
    rospy.sleep(abs(16.0))
    #
    # # Wait for robot back to center Pose
    # at_home = False
    # while not at_home:
    #     world_joint = rospy.wait_for _message('/pr2/world_joint', joint_states)
    #     if abs(world_joint - 0) < 0.1:
    #         at_home = True

    # Loop through the pick list
    for i in range(len(object_list_param)):
        object_name.data = object_list_param[i]['name']
        object_group = object_list_param[i]['group']

        # TODO: Get the PointCloud for a given object and obtain it's centroid
        for j in range(len(labels)):
            if object_name.data == labels[j]:
                # print
                x = centroids[j][0]
                y = centroids[j][1]
                z = centroids[j][2]
                pick_pose.position.x = np.asscalar(x)
                pick_pose.position.y = np.asscalar(y)
                pick_pose.position.z = np.asscalar(z)

        # TODO: Create 'place_pose' for the object
        for j in range(len(dropbox_param)):
            if object_group == dropbox_param[j]['group']:
                x = dropbox_param[j]['position'][0]
                y = dropbox_param[j]['position'][1]
                z = dropbox_param[j]['position'][2]
                place_pose.position.x = x
                place_pose.position.y = y#.item()
                place_pose.position.z = z#.item()

        # Assign the arm to be used for pick_place
        group = object_list_param[i]['group']
        if object_group == 'red':
            arm_name.data = 'left'
        elif object_group == 'green':
            arm_name.data = 'right'

        # # TODO: Create a list of dictionaries (made with make_yaml_dict()) for later output to yaml format
        # yaml_dict = make_yaml_dict(test_scene_num, arm_name, object_name, pick_pose, place_pose)
        # dict_list.append(yaml_dict)

        ## Update obstacles
        obstacle_cloud = cloud_table
        if i < len(object_list_param)-1:
            k=0
            for k in range(i+1, len(object_list)):
                print "list=",len(object_list),", k=",k,"i=",i
                object1 = object_list[k]
                pcl_object1 = ros_to_pcl(object1.cloud)
                obstacle_cloud = merge_cloud(obstacle_cloud, pcl_object1)
        ros_cloud_obstacle = pcl_to_ros(obstacle_cloud)
        pcl_obstacle_pub.publish(ros_cloud_obstacle)


        # Wait for 'pick_place_routine' service to come up
        rospy.wait_for_service('pick_place_routine')

        try:
            pick_place_routine = rospy.ServiceProxy('pick_place_routine', PickPlace)

            # TODO: Insert your message variables to be sent as a service request
            # resp = pick_place_routine(TEST_SCENE_NUM, OBJECT_NAME, WHICH_ARM, PICK_POSE, PLACE_POSE)
            resp = pick_place_routine(test_scene_num, object_name, arm_name, pick_pose, place_pose)

            print ("Response: ",resp.success)

        except rospy.ServiceException, e:
            print "Service call failed: %s"%e

    # Output your request parameters into output yaml file
    send_to_yaml(yaml_filename, dict_list)


if __name__ == '__main__':

    # ROS node initialization
    rospy.init_node('clustering', anonymous=True)

    # Create Subscribers
    pcl_sub = rospy.Subscriber("/pr2/world/points", pc2.PointCloud2,pcl_callback, queue_size=1)


    # Create Publishers
    pcl_objects_pub = rospy.Publisher("/pcl_objects", PointCloud2, queue_size=1)
    pcl_table_pub = rospy.Publisher("/pcl_table", PointCloud2, queue_size=1)
    pcl_cluster_pub = rospy.Publisher("/pcl_cluster", PointCloud2, queue_size=1)

    object_markers_pub = rospy.Publisher("/object_markers", Marker, queue_size=1)
    detected_objects_pub = rospy.Publisher("/detected_objects", DetectedObjectsArray, queue_size=1)

    # added for updating detected obstacles
    pcl_obstacle_pub = rospy.Publisher("/pr2/3D_map/points", PointCloud2, queue_size=1)

    # added for commanding robot to rotate in world joint
    world_joint_pub = rospy.Publisher("/pr2/world_joint_controller/command", Float64, queue_size=10)

    # Load Model From disk
    model = pickle.load(open('model.sav', 'rb'))
    clf = model['classifier']
    encoder = LabelEncoder()
    encoder.classes_ = model['classes']
    scaler = model['scaler']

    # Initialize color_list
    get_color_list.color_list = []

    # Spin while node is not shutdown
    while not rospy.is_shutdown():
        rospy.spin()
