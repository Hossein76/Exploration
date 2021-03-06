#!/usr/bin/env python

import rospy;
import math;
import threading;
import numpy as np;
from nav_msgs.srv import GetPlan ,GetPlanRequest;
from nav_msgs.msg import Path , OccupancyGrid, Odometry;
from communication_node.msg import Data_Goal,Data_Map;
from geometry_msgs.msg import Point

import roslib;
import actionlib;
from actionlib_msgs.msg import *;
from move_base_msgs.msg import *;

name_space="robot1";
robot_number=0;
number_of_robots=0;
######################
merged_map_lock=threading.Lock()
merged_map=None;
######################
map_publisher=None;
goal_publisher=None;
#############
robot_x=0;
robot_y=0;
#################3
beta=1;
utility=1;
laser_range=30;
#################
my_server=None;
goals_list=[];
goals_list_lock=threading.Lock();
other_robots_list=[];
############################
map_pub_frequnecy=2;
map_pub_counter=0;
###############################
move_base_cancel_publisher=None;
simple_action_client=None
current_goal_status = 0 ; # goal status--- PENDING=0--- ACTIVE=1---PREEMPTED=2--SUCCEEDED=3--ABORTED=4---REJECTED=5--PREEMPTING=6---RECALLING=7---RECALLED=8---LOST=9

#########################

class MyWrapper:
    def __init__(self,list_index,robot_name_space):
        self.list_index=list_index;
        self.robot_name_space=robot_name_space;
        self.map_subscriber=rospy.Subscriber("/"+name_space+"/inbox_Map", Data_Map, self.set_Map);
        self.goal_subscriber = rospy.Subscriber("/"+name_space+"/inbox_Goal", Data_Goal, self.set_Goal);
    def set_Map(self,map_data):
        global merged_map_lock;
        global merged_map;
        merged_map_lock.acquire();
        if(merged_map==None):
            merged_map_lock.release();
            return;
        temp_map=np.array([map_data.data.data,merged_map.data]);
        merged_map.data=list(np.max(temp_map,axis=0));
        merged_map_lock.release();
    def set_Goal(self, goal_data):
        global goals_list,goals_list_lock;
        goals_list_lock.acquire()
        goals_list[self.list_index]=goal_data.data;
        goals_list_lock.release();

################################################
################################################
def frontier_is_new(new_frontier,frontiers_list):
    for i in frontiers_list:
        if(math.sqrt((new_frontier[0]-i[0]) ** 2 + (new_frontier[1]-i[1]) ** 2)<2):
            return False;
    return True;

def get_frontiers(map_data):
        print("going for frointiers")
        frontiers=[];
        map_width=int( map_data.info.width); #max of x
        map_height=int(map_data.info.height);#max of y
        map_size=map_height*map_width;
        temp_list=[-1,0,1];
        for y in range(0,map_height):
            for x in range(0,map_width):
                counter=0;
                if map_data.data[(y*map_width)+x]<0:
                    for i in temp_list:
                        for j in temp_list:
                            if (y+i)*map_width+(x+j)<map_size:
                                if(map_data.data[(y+i)*map_width+(x+j)]>=0 and map_data.data[(y+i)*map_width+(x+j)]<10):
                                    counter+=1;
                    if (counter>1 and counter<4):
                        temp_x=(x)*map_data.info.resolution+map_data.info.origin.position.x;
                        temp_y=(y)*map_data.info.resolution+map_data.info.origin.position.y;
                        if(frontier_is_new([temp_x,temp_y],frontiers)==True):
                            frontiers.append([temp_x,temp_y]);


        print("this is number of fronteirs", len(frontiers))
        return list(frontiers);

def compute_frontier_distance(frontiers):
    global robot_x,robot_y;
    frontier_distances=[];
    temp=-2;
    for i in frontiers:
        temp=-2;
        while temp==-2:
            temp=request(robot_x,robot_y,i[0],i[1]);
        frontier_distances.append([i[0],i[1],utility-beta*temp]);
    return list(frontier_distances);

################################################
################################################
def callback_goal_status(data):
    global current_goal_status;
    if len(data.status_list)==0 :
        return;
    current_goal_status = data.status_list[len(data.status_list) - 2].status;

def move_base_tools():
    global move_base_cancel_publisher;
    global simple_action_client;
    global name_space;
    global move_base_status_subscriber;
    move_base_cancel_publisher=rospy.Publisher("/"+name_space+"/move_base/cancel",GoalID,queue_size=10);
    simple_action_client = actionlib.SimpleActionClient("/"+name_space+"/move_base", MoveBaseAction);
    simple_action_client.wait_for_server();
    print(name_space,"move base tools are ok")
    move_base_status_subscriber=rospy.Subscriber("/"+name_space+"/move_base/status", GoalStatusArray, callback_goal_status);


################################################
################################################################################################
################################################


def create_service():
    global my_server,name_space;
    rospy.wait_for_service("/"+name_space+"/move_base/NavfnROS/make_plan");
    try:
            my_server = rospy.ServiceProxy("/"+name_space+"/move_base/NavfnROS/make_plan", GetPlan)
            print (name_space,"server found")
    except rospy.ServiceException:
            print (name_space,"Service not found failed ")



def request(sx,sy,gx,gy):
    request = GetPlanRequest();
    request.start.header.frame_id="/"+name_space+"/map";
    request.start.pose.position.x=sx;
    request.start.pose.position.y=sy;
    request.start.pose.orientation.w=1.0;
    request.goal.header.frame_id="/"+name_space+"/map";
    request.goal.pose.position.x=gx;
    request.goal.pose.position.y=gy;
    request.goal.pose.orientation.w=1.0;
    request.tolerance=0.5
    try:
        response = my_server(request)
        if(len(response.plan.poses)==0):
            #print(name_space,"no path");
            return 1000000;
        x=(response.plan.poses[0].pose.position.x);
        y=(response.plan.poses[0].pose.position.y);
        sum_path=0;
        for i in response.plan.poses:
            sum_path+=math.sqrt( (i.pose.position.x-x)**2 +  (i.pose.position.y-y)**2);
            x=(i.pose.position.x)
            y=(i.pose.position.y)
        #print(sum_path)
        return sum_path;
    except rospy.ServiceException:
        print ("sending the request failed");
        return -2;


def send_goal(goal_x,goal_y):
    global other_robots_list,goal_publisher;
    global name_space;
    global simple_action_client;
    for i in other_robots_list:
        new_data=Data_Goal();
        new_data.source=name_space;
        new_data.destination=i.robot_name_space;
        new_data.data=Point(goal_x,goal_y,0.0);
        goal_publisher.publish(new_data);

    goal = MoveBaseGoal();
        # set goal
    goal.target_pose.pose.position.x = goal_x;
    goal.target_pose.pose.position.y = goal_y;
    goal.target_pose.pose.orientation.w = 1.0;
    goal.target_pose.pose.orientation.z = 0;
    goal.target_pose.header.frame_id = "/map";
    goal.target_pose.header.stamp = rospy.Time.now();
        # start listener
        # send goal
    print(name_space,"sent goal")
    simple_action_client.send_goal(goal);

################################################
################################################
def map_callback(map_data):
    global merged_map,merged_map_lock;
    global other_robots_list;
    global map_publisher;
    global map_pub_counter,map_pub_frequnecy;
    merged_map_lock.acquire();
    if (merged_map==None):
        merged_map=map_data;
    else:
        temp_map2=list(merged_map.data);
        merged_map=map_data;
        temp_map=np.array([map_data.data,list(temp_map2)]);
        merged_map.data=list(np.max(temp_map,axis=0));
    merged_map_lock.release();
    if (map_pub_counter==0):
        for i in other_robots_list:
            new_data=Data_Map();
            new_data.source=name_space;
            new_data.destination=i.robot_name_space;
            new_data.data=map_data;
            map_publisher.publish(new_data);
    elif(map_pub_counter>=10):
        map_pub_counter=0;
    else:
        map_pub_counter+=map_pub_frequnecy;


def odom_callback(odom_data):
    global robot_x,robot_y;
    robot_x=odom_data.pose.pose.position.x;
    robot_y=odom_data.pose.pose.position.y;
################################################
################################################

def burgard():
    global merged_map_lock;
    global merged_map;
    global name_space;
    global goals_list;
    global goals_list_lock;
    while(merged_map==None):
        pass;
    while not rospy.is_shutdown():
        merged_map_lock.acquire();
        print("going for frointiers")
        frontiers=get_frontiers(merged_map);
        merged_map_lock.release();
        if (len(frontiers)==0):
            print(name_space,"no new frontiers");
            exit();
        frontiers=compute_frontier_distance(frontiers);
        print("we have frontiers")
        if (len(frontiers)==0):
            print(name_space,"no path to frointiers");
            exit();
        for i in range(0,len(frontiers)):
            goals_list_lock.acquire();
            for j in goals_list:
                if(j==None):continue;
                temp_distance=math.sqrt( (j.x-frontiers[i][0])**2 +  (j.y-frontiers[i][1])**2);
                if(temp_distance<=laser_range):
                    frontiers[i][2]-=(1-temp_distance/laser_range);
            goals_list_lock.release();
        print("sorting")
        frontiers.sort(key=lambda node: node[2]);
        send_goal(frontiers[0][0],frontiers[0][1]);
        rate = rospy.Rate(0.5);
        while current_goal_status==3 or current_goal_status==4 or current_goal_status==5 or current_goal_status==9:
            rate.sleep();


def main():
    global name_space,robot_number,number_of_robots;
    global merged_map,goals_list,other_robots_list;
    global goal_publisher;
    global map_publisher;
    rospy.init_node("burgard_exploration_node");
    name_space = rospy.get_param("namespace", default="robot1");
    robot_number=int(name_space[-1]);
    number_of_robots=(int(rospy.get_param("number_of_robots", default=1)));
    temp_i=0;
    for i in range (0,number_of_robots):
        if (i==robot_number):continue;
        goals_list.append(None);
        other_robots_list.append(MyWrapper(list_index=temp_i,robot_name_space="robot"+str(i)));
        temp_i+=1;
    create_service();
    move_base_tools();
    map_subscriber=rospy.Subscriber("/"+name_space+"/map", OccupancyGrid, map_callback);
    odom_subscriber=rospy.Subscriber("/"+name_space+"/odom", Odometry, odom_callback);
    goal_publisher=rospy.Publisher("/message_server_Goal", Data_Goal,queue_size=15);
    map_publisher=rospy.Publisher("/message_server_map", Data_Map,queue_size=15);
    burgard();
    rospy.spin();

if __name__ == '__main__':
    main();
