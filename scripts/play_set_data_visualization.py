"""
pcd_obs_env with:
1. object/background segmentation
2. object registration
3. goal sampling
4. reward calculation
"""

import numpy as np
from PIL import Image as im 
import os
import argparse
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import numpy as np
import open3d as o3d
import numpy as np
from ctypes import * # convert float to uint32
# from matplotlib import pyplot as plt
import copy

# import rospy
# import rosbag
from std_msgs.msg import Header
from sensor_msgs.msg import PointCloud2, PointField
# import sensor_msgs.point_cloud2 as pc2
from numpy.linalg import inv
# from lib_cloud_conversion_between_Open3D_and_ROS import convertCloudFromRosToOpen3d
from scipy.spatial.transform import Rotation


def get_init_trans(src, dst):
    if(src.shape[0] == 3):
        src = np.transpose(src)
    if(dst.shape[0] == 3):
        dst = np.transpose(dst)
    trans = np.mean(src, axis = 0) - np.mean(dst, axis = 0)
    trans = trans.reshape(3,1)
    return trans


def print_plot(F_reg, src, dst, dir, idx = 0,  save = False):
    rot = F_reg[0:3, 0:3]
    trans = F_reg[0:3, 3]
    
    trans = trans.reshape(3,1)
    print("rot: ", rot)
    print("trans: ", trans)
    pcd = rot @ np.transpose(dst) + trans
    plot_func( src, pcd , dir, idx = idx, save = save)
    
def display_inlier_outlier(cloud, ind):
    inlier_cloud = cloud.select_by_index(ind)
    outlier_cloud = cloud.select_by_index(ind, invert=True)
    print("Showing outliers (red) and inliers (gray): ")
    outlier_cloud.paint_uniform_color([1, 0, 0])
    inlier_cloud.paint_uniform_color([0.8, 0.8, 0.8])
    o3d.visualization.draw_geometries([inlier_cloud])

def draw_registration_result_original_color(source, target, transformation):
    source_temp = copy.deepcopy(source)
    source_temp.transform(transformation)
    o3d.visualization.draw_geometries([source_temp, target],
                                      zoom=0.5,
                                      front=[-0.2458, -0.8088, 0.5342],
                                      lookat=[1.7745, 2.2305, 0.9787],
                                      up=[0.3109, -0.5878, -0.7468])

def draw_registration_result(source, target, transformation):
    source_temp = copy.deepcopy(source)
    target_temp = copy.deepcopy(target)
    source_temp.paint_uniform_color([1, 0.706, 0])
    target_temp.paint_uniform_color([0, 0.651, 0.929])
    source_temp.transform(transformation)
    o3d.visualization.draw_geometries([source_temp, target_temp])

def colored_ICP(source, target):
    voxel_radius = [0.002, 0.002, 0.002]
    max_iter = [50, 30, 14]
    current_transformation = np.identity(4)
    print("3. Colored point cloud registration")
    for scale in range(3):
        iter = max_iter[scale]
        radius = voxel_radius[scale]
        print([iter, radius, scale])

        print("3-1. Downsample with a voxel size %.2f" % radius)
        source_down = source.voxel_down_sample(radius)
        target_down = target.voxel_down_sample(radius)

        print("3-2. Estimate normal.")
        source_down.estimate_normals(
            o3d.geometry.KDTreeSearchParamHybrid(radius=radius * 2, max_nn=30))
        target_down.estimate_normals(
            o3d.geometry.KDTreeSearchParamHybrid(radius=radius * 2, max_nn=30))

        print("3-3. Applying colored point cloud registration")
        result_icp = o3d.pipelines.registration.registration_colored_icp(
            source_down, target_down, radius, current_transformation,
            o3d.pipelines.registration.TransformationEstimationForColoredICP(),
            o3d.pipelines.registration.ICPConvergenceCriteria(relative_fitness=1e-6,
                                                            relative_rmse=1e-6,
                                                            max_iteration=iter))
        current_transformation = result_icp.transformation
        print(result_icp)
    draw_registration_result_original_color(source, target,
                                            result_icp.transformation)


def get_transform( trans, quat):
    t = np.eye(4)
    t[:3, :3] = Rotation.from_quat( quat ).as_matrix()
    t[:3, 3] = trans
    # print(t)
    return t

def get_cube_corners( bound_box ):
    corners = []
    corners.append( [ bound_box[0][0], bound_box[1][0], bound_box[2][0] ])
    corners.append( [ bound_box[0][0], bound_box[1][1], bound_box[2][0] ])
    corners.append( [ bound_box[0][1], bound_box[1][1], bound_box[2][0] ])
    corners.append( [ bound_box[0][1], bound_box[1][0], bound_box[2][0] ])

    return corners

def visualize_pcd(pcd, left = None, right = None):
    coor_frame = o3d.geometry.TriangleMesh.create_coordinate_frame()
    vis = o3d.visualization.VisualizerWithKeyCallback()
    vis.create_window()
    coor_frame.scale(0.1, center=(0., 0., 0.))
    vis.add_geometry(coor_frame)
    vis.get_render_option().background_color = np.asarray([255, 255, 255])

    view_ctl = vis.get_view_control()

    vis.add_geometry(pcd)

    mesh = o3d.geometry.TriangleMesh.create_coordinate_frame()
    mesh.scale(0.1, center=(0., 0., 0.) )
    
    # left_mesh.scale(0.1, center=(left[0][3], left[1][3], left[2][3]))

    # right_mesh.scale(0.1, center=(right[0][3], right[1][3], right[2][3]))
    
    if left is not None:
        for trans in left:
            left_mesh = copy.deepcopy(mesh).transform(trans)
            vis.add_geometry(left_mesh)

    if right is not None:
        for trans in right:
            right_mesh = copy.deepcopy(mesh).transform(trans)
            vis.add_geometry(right_mesh)
    
    # view_ctl.set_up([-0.4, 0.0, 1.0])
    # view_ctl.set_front([-4.02516493e-01, 3.62146675e-01, 8.40731978e-01])
    # view_ctl.set_lookat([0.0 ,0.0 ,0.0])
    
    view_ctl.set_up((1, 0, 0))  # set the positive direction of the x-axis as the up direction
    # view_ctl.set_up((0, -1, 0))  # set the negative direction of the y-axis as the up direction
    view_ctl.set_front((-0.3, 0.0, 0.2))  # set the positive direction of the x-axis toward you
    view_ctl.set_lookat((0.0, 0.0, 0.3))  # set the original point as the center point of the window
    vis.run()
    vis.destroy_window()

def project_color( point_3d, color, image, extrinsic, intrinsic):
                
    point4d = np.append(point_3d, 1)
    new_point4d = np.matmul(extrinsic, point4d)
    point3d = new_point4d[:-1]
    zc = point3d[2]
    new_point3d = np.matmul(intrinsic, point3d)
    new_point3d = new_point3d/new_point3d[2]
    u = int(round(new_point3d[0]))
    v = int(round(new_point3d[1]))
    if(v<0 or v>= image.shape[0] or u<0 or u>= image.shape[1]):
        return image
    
    image[max(0, v-5): min(v+5, image.shape[0]), max(0, u-5): min(u+5, image.shape[1]) ] = color
    # print("updated")
    return image
def main():
    
    parser = argparse.ArgumentParser(description="extract interested object and traj from rosbag")
    # parser.add_argument("-b", "--bag_in", default="./data/yellow_handle_mug.bag",  help="Input ROS bag name.")
    parser.add_argument("-t", "--task_dir", default="./play_set_dataset",  help="Input ROS bag name.")
    parser.add_argument("-d", "--data_id", default="1", help="data idx")
    args = parser.parse_args()
    
    # task_dir = "./play_around"
    task_dir = args.task_dir
    data_id = args.data_id
    print("processing data: ", data_id)
    data = np.load( task_dir + "/" + data_id + ".npy", allow_pickle = True)

    make_video = True

    cam_extrinsic = get_transform( [-0.13913296, 0.053, 0.43643044], [-0.63127772, 0.64917582, -0.31329509, 0.28619116])
    cam_intrinsic_np = np.array([
        [734.1779174804688, 0., 993.6226806640625],
        [0. ,734.1779174804688,  551.8895874023438],
        [0., 0., 1.0]
    ])

    o3d_intrinsic = o3d.camera.PinholeCameraIntrinsic(1920, 1080, 734.1779174804688, 734.1779174804688, 993.6226806640625, 551.8895874023438)

    # for point in data:
    #     bgr = point['bgr']
    #     rgb = bgr[...,::-1].copy()
    #     xyz = point['xyz']/1000.0
    #     xyz = xyz.reshape(-1,3)
    #     print("xyz: ", xyz.shape)

    #     rgb = rgb.reshape(-1,3)
    #     rgb = rgb.astype(float)
    #     bgr = bgr.reshape(-1,3)
    #     print("rgb: ", rgb.shape)
    #     pcd = o3d.geometry.PointCloud()
    #     pcd.points = o3d.utility.Vector3dVector(xyz)
    #     pcd.colors = o3d.utility.Vector3dVector(rgb/255.0)
    #     print(pcd)
    #     visualize_pcd(pcd)
    video_images = []

    max_diff = 0.065
    left_min_joint = 0.638
    left_max_joint = 1.626

    right_min_joint = 0.625
    right_max_joint = 1.610


    for idx, point in enumerate( data, 0 ):

        # if(idx < 100):
        #     continue
        # if(idx % 20 != 0):
        #     continue

        bgr = point['bgr']
        rgb = bgr[...,::-1].copy()

        depth = point['depth']
        # depth = depth.reshape(-1,3)
        # print("depth: ", depth.shape)

        # rgb = rgb.reshape(-1,3)
        # rgb = rgb.astype(float)
        # bgr = bgr.reshape(-1,3)
        # print("rgb: ", rgb.shape)
        # pcd = o3d.geometry.PointCloud()

        im_color = o3d.geometry.Image(rgb)
        im_depth = o3d.geometry.Image(depth)
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            im_color, im_depth, depth_scale=1000, depth_trunc=2000, convert_rgb_to_intensity=False)
        
        final_pcd = o3d.geometry.PointCloud.create_from_rgbd_image(
                rgbd,
                o3d_intrinsic
            )
        final_pcd = final_pcd.transform(cam_extrinsic)
        mesh = o3d.geometry.TriangleMesh.create_coordinate_frame()

        left_transform = get_transform(point['left_ee'][0:3], point['left_ee'][3:7] )
        right_transform = get_transform(point['right_ee'][0:3], point['right_ee'][3:7] ) 
      
        # play set
        left_transform = left_transform @ get_transform( [ -0.055, 0.015, -0.005], [0., 0., 0., 1.] )
        right_transform = right_transform @ get_transform( [-0.05, -0.005, -0.01], [0., 0., 0., 1.] )

        # left_transform = left_transform @ get_transform( [ -0.075, 0.005,  -0.005], [0., 0., 0., 1.] )
        # right_transform = right_transform @ get_transform( [-0.05, 0.005, -0.005], [0., 0., 0., 1.] )

 
        assigned_color = np.array([0,0,255])
        point_3d = np.array( [ left_transform[0][3], left_transform[1][3], left_transform[2][3] ])
        bgr = project_color(point_3d, assigned_color, bgr, inv(cam_extrinsic), cam_intrinsic_np)

        point_3d = np.array( [ right_transform[0][3], right_transform[1][3], right_transform[2][3] ])
        bgr = project_color(point_3d, assigned_color, bgr, inv(cam_extrinsic), cam_intrinsic_np)

        # visualize_pcd(final_pcd, [left_transform], [right_transform])

        # left tips
        openness = np.clip( point["left_pos"][6], left_min_joint, left_max_joint)
        left_gripper_distance = (openness - left_min_joint) / (left_max_joint - left_min_joint) * max_diff / 2.0
        left_y = left_gripper_distance
        right_y = -1*left_gripper_distance
        lh_left_tip = left_transform @ get_transform([0.09, left_y, 0.], [0., 0., 0., 1.] )
        lh_right_tip = left_transform @ get_transform([0.09, right_y, 0.0], [0., 0., 0., 1.]  )
        # print("difference: ", left_y - right_y)
        # max_diff = max(max_diff, left_y - right_y)
        # min_joint = min(min_joint, point["left_pos"][6])
        # max_joint = max(max_joint, point["left_pos"][6])
        # visualize_pcd(final_pcd, [left_transform, lh_left_tip, lh_right_tip], [right_transform])
        point_3d = np.array( [ lh_left_tip[0][3], lh_left_tip[1][3], lh_left_tip[2][3] ])
        bgr = project_color(point_3d, assigned_color, bgr, inv(cam_extrinsic), cam_intrinsic_np)
        point_3d = np.array( [ lh_right_tip[0][3], lh_right_tip[1][3], lh_right_tip[2][3] ])
        bgr = project_color(point_3d, assigned_color, bgr, inv(cam_extrinsic), cam_intrinsic_np)


        # right tips
        openness = np.clip( point["right_pos"][6], right_min_joint, right_max_joint)
        right_gripper_distance = (openness - right_min_joint) / (right_max_joint - right_min_joint) * max_diff / 2.0
        left_y = right_gripper_distance
        right_y = -1*right_gripper_distance
        rh_left_tip = right_transform @ get_transform([0.09, left_y, 0.], [0., 0., 0., 1.] )
        rh_right_tip = right_transform @ get_transform([0.09, right_y, 0.0], [0., 0., 0., 1.]  )
        # print("difference: ", left_y - right_y)
        # max_diff = max(max_diff, left_y - right_y)
        # min_joint = min(min_joint, point["left_pos"][6])
        # max_joint = max(max_joint, point["left_pos"][6])
        # visualize_pcd(final_pcd, [left_transform], [right_transform, rh_left_tip, rh_right_tip])
        point_3d = np.array( [ rh_left_tip[0][3], rh_left_tip[1][3], rh_left_tip[2][3] ])
        bgr = project_color(point_3d, assigned_color, bgr, inv(cam_extrinsic), cam_intrinsic_np)
        point_3d = np.array( [ rh_right_tip[0][3], rh_right_tip[1][3], rh_right_tip[2][3] ])
        bgr = project_color(point_3d, assigned_color, bgr, inv(cam_extrinsic), cam_intrinsic_np)
        
        
        # visualize_pcd(final_pcd, [left_transform, lh_left_tip, lh_right_tip], [right_transform, rh_left_tip, rh_right_tip])

        if make_video:
            video_images.append(bgr)
        
    # print("max_diff: ", max_diff)
    # print("min_joint: ", min_joint)
    # print("max_joint: ", max_joint)

    if make_video:
        video_name = 'video{}.avi'.format(data_id)
        height, width, layers = video_images[0].shape
        video = cv2.VideoWriter(video_name, 0, 15, (width,height))
        for image in video_images:
            video.write(image)
        video.release()

if __name__ == "__main__":
    main()
