from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import authenticate
from django.db.models import Q, Count
from django.utils import timezone
from .models import User, Project, Task, ProjectMember
from .serializers import (
    UserSerializer, UserRegisterSerializer, 
    ProjectSerializer, TaskSerializer
)

class CustomTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            user = User.objects.get(username=request.data['username'])
            response.data['user'] = UserSerializer(user).data
        return response

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_permissions(self):
        if self.action == 'create':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
    
    def create(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return Project.objects.all()
        return Project.objects.filter(
            Q(created_by=user) | Q(members=user)
        ).distinct()
    
    def perform_create(self, serializer):
        project = serializer.save(created_by=self.request.user)
        # Add creator as member
        ProjectMember.objects.create(project=project, user=self.request.user)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def add_member(self, request, pk=None):
        project = self.get_object()
        email = request.data.get('email')
        
        try:
            user = User.objects.get(email=email)
            ProjectMember.objects.get_or_create(project=project, user=user)
            return Response({'message': 'Member added successfully'})
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        project_id = self.request.query_params.get('project_id')
        
        if project_id:
            # Check if user has access to project
            project = Project.objects.filter(id=project_id).first()
            if not project:
                return Task.objects.none()
            
            has_access = (
                user.role == 'admin' or 
                project.created_by == user or 
                ProjectMember.objects.filter(project=project, user=user).exists()
            )
            
            if not has_access:
                return Task.objects.none()
            
            return Task.objects.filter(project_id=project_id)
        
        return Task.objects.filter(
            Q(project__created_by=user) | 
            Q(project__members=user) |
            Q(assigned_to=user)
        ).distinct()
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        user = request.user
        
        # Members can only update status of their assigned tasks
        if user.role != 'admin':
            if instance.assigned_to != user:
                return Response(
                    {'error': 'You can only update tasks assigned to you'},
                    status=status.HTTP_403_FORBIDDEN
                )
            # Only allow status update
            if set(request.data.keys()) - {'status'}:
                return Response(
                    {'error': 'Members can only update task status'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        return super().update(request, *args, **kwargs)