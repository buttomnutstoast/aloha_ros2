#3dda data:
# rgbd image 1920*1080 need post process
# start from everywhere
# episode length 10~100 steps
# joints position & velocity


import math

from geometry_msgs.msg import Twist

import rclpy
from rclpy.node import Node

from tf2_ros import TransformException
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener

from sensor_msgs.msg import Joy
from geometry_msgs.msg import PointStamped, TwistStamped, Quaternion, Vector3, TransformStamped
from std_msgs.msg import String, Float32, Int8, UInt8, Bool, UInt32MultiArray, Int32
import numpy as np 
import time

from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2 
from rclpy.qos import QoSProfile
from rclpy.clock import Clock
from message_filters import Subscriber, ApproximateTimeSynchronizer

from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
from tf2_ros import TransformBroadcaster
class DataCollector(Node):

    def __init__(self):
        super().__init__('aloha_3dda_data_collection_node')
        # print("in init")
        # Declare and acquire `target_frame` parameter
        self.left_hand_frame = "follower_left/ee_gripper_link"
        self.right_hand_frame = "follower_right/ee_gripper_link"
        # self.left_base_frame = "follower_left/base_link"
        # self.right_base_frame = "follower_right/base_link"
        self.left_base_frame = "world"
        self.right_base_frame = "world"

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.left_hand_transform = TransformStamped()
        self.right_hand_transform = TransformStamped()

        #axes
        self.left_joystick_x = 0
        self.left_joystick_y = 1
        self.l2 = 2
        self.right_joystick_x = 3
        self.right_joystick_y = 4
        self.right_trigger = 5
        self.leftside_left_right_arrow = 6
        self.l = leftside_up_down_arrow = 7

        self.max_idx = 7
        
        # button mapping for wireless controller
        self.x_button = 0
        self.o_button = 1
        self.triangle_button = 2
        self.square_button = 3

        self.l1 = 4
        self.r1 = 5
        self.l2 = 6
        self.r2 = 7
        self.share_button = 8
        self.opotions_button = 9
        self.max_button = 9

        # states
        self.recording = False

        self.last_data_time = time.time()
        # data
        self.current_stack = []

        self.success_stop_pressed_last = False
        self.failure_stop_pressed_last = False
        
        # Call on_timer function every second
        self.timer_period = 0.01
        # self.timer = self.create_timer( self.timer_period, self.on_timer )
        self.joystick_sub = self.create_subscription(Joy, "/joy", self.joyCallback,1)
        self.br = CvBridge()
        # self.subscription = self.create_subscription(Image, "/camera_1/left_image", self.img_callback, 1)
        

        queue_size = 10
        max_delay = 0.01 #10ms
        self.time_diff = 1.0

        self.tf_broadcaster = TransformBroadcaster(self)

        # self.rgb_sub = Subscriber(self, Image, "/camera_1/left_image")
        # self.depth_sub = Subscriber(self, Image, "/camera_1/depth")
        self.rgb_sub = Subscriber(self, Image, "/zed/zed_node/depth/depth_registered")
        self.depth_sub = Subscriber("/zed/zed_node/left/image_rect_color")
        self.time_sync = ApproximateTimeSynchronizer([self.rgb_sub, self.depth_sub],
                                                     queue_size, max_delay)
        self.time_sync.registerCallback(self.SyncCallback)

        timer_period = 0.01 #100hz
        self.timer = self.create_timer(timer_period, self.publish_tf)
    
    def publish_tf(self):
        left_t = TransformStamped()
        right_t = TransformStamped()
        master_cam_t = TransformStamped()
        # # Read message content and assign it to
        # # corresponding tf variables
        ros_time = self.get_clock().now()
        left_t.header.stamp = ros_time.to_msg()
        right_t.header.stamp = ros_time.to_msg()
        master_cam_t.header.stamp = ros_time.to_msg()

        left_t.header.frame_id = 'world'
        left_t.child_frame_id = "follower_left/base_link"
        left_t.transform.translation.x = 0.0
        left_t.transform.translation.y = -0.315
        left_t.transform.translation.z = 0.0
        left_t.transform.rotation.x = 0.0
        left_t.transform.rotation.y = 0.0
        left_t.transform.rotation.z = 0.0
        left_t.transform.rotation.w = 1.0

        right_t.header.frame_id = 'world'
        right_t.child_frame_id = "follower_right/base_link"
        right_t.transform.translation.x = 0.0
        right_t.transform.translation.y = 0.315
        right_t.transform.translation.z = 0.0
        right_t.transform.rotation.x = 0.0
        right_t.transform.rotation.y = 0.0
        right_t.transform.rotation.z = 0.0
        right_t.transform.rotation.w = 1.0

        master_cam_t.header.frame_id = 'world'
        master_cam_t.child_frame_id = "master_cam"
        master_cam_t.transform.translation.x = -0.13913296
        master_cam_t.transform.translation.y = 0.053
        master_cam_t.transform.translation.z = 0.43643044
        master_cam_t.transform.rotation.x = -0.63127772
        master_cam_t.transform.rotation.y = 0.64917582
        master_cam_t.transform.rotation.z = -0.31329509
        master_cam_t.transform.rotation.w = 0.28619116

        # # Send the transformation
        self.tf_broadcaster.sendTransform(left_t)
        self.tf_broadcaster.sendTransform(right_t)
        self.tf_broadcaster.sendTransform(master_cam_t)

    def SyncCallback(self, rgb, depth):
        # print("rgb timestamp:", rgb.header)
        # print("depth timestamp: ", depth.header)
        data_time = time.time()
        if(data_time - self.last_data_time < self.time_diff):
            return
        
        try:
            self.left_hand_transform = self.tf_buffer.lookup_transform(
                    self.left_hand_frame,
                    self.left_base_frame,
                    rgb.header.stamp,
                    timeout=rclpy.duration.Duration(seconds=0.01)
                )
        except TransformException as ex:
            self.get_logger().info(
                f'Could not transform {self.left_base_frame} to {self.left_hand_frame}: {ex}'
            )
            return

        try:
            self.right_hand_transform = self.tf_buffer.lookup_transform(
                    self.right_hand_frame,
                    self.right_base_frame,
                    rgb.header.stamp,
                    timeout=rclpy.duration.Duration(seconds=0.01)
                )
        except TransformException as ex:
            self.get_logger().info(
                f'Could not transform {self.right_base_frame} to {self.right_hand_frame}: {ex}'
            )
            return
        
        left_x = self.left_hand_transform.transform.translation.x
        left_y = self.left_hand_transform.transform.translation.y
        left_z = self.left_hand_transform.transform.translation.z
        left_qx = self.left_hand_transform.transform.rotation.x
        left_qy = self.left_hand_transform.transform.rotation.y
        left_qz = self.left_hand_transform.transform.rotation.z
        left_qw = self.left_hand_transform.transform.rotation.w

        right_x = self.right_hand_transform.transform.translation.x
        right_y = self.right_hand_transform.transform.translation.y
        right_z = self.right_hand_transform.transform.translation.z
        right_qx = self.right_hand_transform.transform.rotation.x
        right_qy = self.right_hand_transform.transform.rotation.y
        right_qz = self.right_hand_transform.transform.rotation.z
        right_qw = self.right_hand_transform.transform.rotation.w

        current_state = {}
        current_state["left_ee"] = np.array([left_x, left_y, left_z, left_qx, left_qy, left_qz, left_qw])
        current_state["right_ee"] = np.array([right_x, right_y, right_z, right_qx, right_qy, right_qz, right_qw])
        current_state["rgb"] = np.array(self.br.imgmsg_to_cv2(rgb)) # Todo check rgb order
        current_state["depth"] = np.array(self.br.imgmsg_to_cv2(depth)) # Todo check rgb order

        # print("rgb: ", current_state["rgb"].shape)
        # print("depth: ", current_state["depth"].shape)
        self.last_data_time = data_time
        self.current_stack.append(current_state)

        # print("tf: ", self.left_hand_transform)
        # print("")

    # def img_callback(self, data):
    #     self.get_logger().info('Receiving video frame')
    #     current_frame = self.br.imgmsg_to_cv2(data)
    #     image1_np = np.array(current_frame[:,:,0:3])
        # update current stepfrom rclpy.qos import QoSProfile
    

    def save_data(self):
        now = time.time()
        np.save( str(now), self.current_stack)
    
    def clean_data(self):
        self.current_stack.clear()

    def episode_end(self, success_flag):
        if( success_flag == True):
            self.save_data()
        self.clean_data()

    def on_timer(self):
        # t.transform.translation.x
        try:
            self.left_hand_transform = self.tf_buffer.lookup_transform(
                self.left_hand_frame,
                self.left_base_frame,
                rclpy.time.Time()
            )
        except TransformException as ex:
            self.get_logger().info(
                f'Could not transform {self.left_base_frame} to {self.left_hand_frame}: {ex}'
            )
            return

        try:
            self.right_hand_transform = self.tf_buffer.lookup_transform(
                self.right_hand_frame,
                self.right_base_frame,
                rclpy.time.Time()
            )
        except TransformException as ex:
            self.get_logger().info(
                f'Could not transform {self.right_base_frame} to {self.right_hand_frame}: {ex}'
            )
            return
        # return   
        # print("updated trans:")
        # print("left hand: ", self.left_hand_transform)
        # print("right hand: ", self.right_hand_transform)

    def joyCallback(self, msg):

        start_recording_pressed = msg.buttons[self.triangle_button]
        success_stop_pressed = msg.buttons[self.o_button]
        failure_stop_pressed = msg.buttons[self.x_button]


        if( (start_recording_pressed == True) and (self.start_recording_pressed_last == False) ):
            if( self.recording == False ):
                self.recording = True
                self.get_logger().info('start recording!!!')
                # self.get_logger().info('start recording!!!')
            else:
                self.recording = True
                self.episode_end(False)
                self.get_logger().info('start recording!!!')
                # self.get_logger().info('start recording!!!')                

        if( (success_stop_pressed == True) and (self.success_stop_pressed_last == False) ):
            if( self.recording == True ):
                self.recording = False
                self.episode_end(True)
                self.get_logger().info('episode succeed!!!')
                # self.get_logger().info('episode succeed!!!')

        if( (failure_stop_pressed == True) and (self.failure_stop_pressed_last == False) ):
            if( self.recording == True ):
                self.recording = False
                self.episode_end(False)
                self.get_logger().info('episode failed!!!')
                # self.get_logger().info('episode failed!!!')

        self.start_recording_pressed_last = start_recording_pressed
        self.success_stop_pressed_last = success_stop_pressed           
        self.failure_stop_pressed_last = failure_stop_pressed

def main():

    rclpy.init()
    node = DataCollector()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    rclpy.shutdown()
if __name__ == '__main__':
    main()
