""" Vertex and Edge objects and the machinery belonging to them """
from typing import List, Callable, Union, Tuple

import numpy as np

from classy_blocks.util import functions as f
from classy_blocks.util import constants


class WrongEdgeTypeException(Exception):
    """Raised when using an unsupported edge type"""

    def __init__(self, edge_type, *args, **kwargs):
        raise Exception(f"Wrong edge type: {edge_type}", *args, **kwargs)


def transform_points(points: List[List[float]], function: Callable) -> List[List[float]]:
    """A comprehensive shortcut"""
    return [function(p) for p in points]


def transform_edges(edges: List["Edge"], function: Callable):
    """Same as transform_points but deals with multiple points in an edge, if applicable"""
    if edges is not None:
        new_edges = [None] * 4
        for i, edge_points in enumerate(edges):
            edge_type, edge_points = Edge.get_type(edge_points)

            # spline edge is defined with multiple points,
            # a single point defines an arc;
            # 'project' and 'line' don't require any
            if edge_type == "spline":
                new_edges[i] = [function(e) for e in edge_points]
            elif edge_type == "arc":
                new_edges[i] = function(edge_points)

        return new_edges

    return None


class Vertex:
    """point with an index that's used in block and face definition
    and can output in OpenFOAM format"""

    def __init__(self, point):
        self.point = np.asarray(point)
        self.mesh_index = None  # will be changed in Mesh.prepare_data()

    def rotate(self, angle, axis=[1, 0, 0], origin=[0, 0, 0]):
        """returns a new, rotated Vertex"""
        point = f.arbitrary_rotation(self.point, axis, angle, origin)
        return Vertex(point)

    def __repr__(self):
        s = constants.vector_format(self.point)

        if self.mesh_index is not None:
            s += " // {}".format(self.mesh_index)

        return s


class Edge:
    """An Edge, defined by two vertices and points in between;
    a single point edge is treated as 'arc', more points are
    treated as 'spline'.

    passed indexes refer to position in Block.edges[] list; Mesh.prepare_data()
    will assign actual Vertex objects."""

    def __init__(self, index_1: int, index_2: int, points: Union[List[float], List[List[float]]]):
        # indexes in block.edges[] list
        self.block_index_1 = index_1
        self.block_index_2 = index_2

        # these will refer to actual Vertex objects after Mesh.prepare_data()
        self.vertex_1 = None
        self.vertex_2 = None

        self.type, self.points = self.get_type(points)

    @staticmethod
    def get_type(points: Union[List[float], List[List[float]]]) -> Tuple[str, Union[List[float], List[List[float]]]]:
        """returns edge type and a list of points:
        - None for a straight line,
        - 'project' for projection to geometry,
        - 'arc' for a circular arc,
        - 'spline' for a spline"""

        if points is None:
            return "line", None

        # it 'points' is a string, this is a projected edge;
        if isinstance(points, str):
            return "project", points

        # if multiple points are given check that they are of correct length
        points = np.array(points)
        shape = np.shape(points)

        if len(shape) == 1:
            edge_type = "arc"
        else:
            assert len(shape) == 2
            for p in points:
                assert len(p) == 3

            t = "spline"

            edge_type = "spline"

        return edge_type, points

    @property
    def point_list(self) -> str:
        """Returns a list of points (if applicable), readily
        formatted to be inserted into blockMeshDict"""
        if self.type == "line":
            return None

        if self.type == "project":
            return f"({self.points})"

        if self.type == "arc":
            return constants.vector_format(self.points)

        if self.type == "spline":
            return "(" + " ".join([constants.vector_format(p) for p in self.points]) + ")"

        raise WrongEdgeTypeException(self.type)

    @property
    def is_valid(self):
        # wedge geometries produce coincident
        # edges and vertices; drop those
        if f.norm(self.vertex_1.point - self.vertex_2.point) < constants.tol:
            return False

        # 'all' spline and projected edges are 'valid'
        if self.type in ("line", "spline", "project"):
            return True

        # if case vertex1, vertex2 and point in between
        # are collinear, blockMesh will find an arc with
        # infinite radius and crash.
        # so, check for collinearity; if the three points
        # are actually collinear, this edge is redundant and can be
        # silently dropped
        OA = self.vertex_1.point
        OB = self.vertex_2.point
        OC = self.points

        # if point C is on the same line as A and B:
        # OC = OA + k*(OB-OA)
        AB = OB - OA
        AC = OC - OA

        k = f.norm(AC) / f.norm(AB)
        d = f.norm((OA + AC) - (OA + k * AB))

        return d > constants.tol

    def get_length(self) -> float:
        """Returns an approximate length of this Edge"""
        if self.type in ("line", "project"):
            return f.norm(self.vertex_1.point - self.vertex_2.point)

        if self.type == "arc":
            return f.arc_length_3point(self.vertex_1.point, self.points, self.vertex_2.point)

        def curve_length(points):
            l = 0

            for i in range(len(points) - 1):
                l += f.norm(points[i + 1] - points[i])

            return l

        if self.type == "spline":
            edge_points = np.concatenate(([self.vertex_1.point], self.points, [self.vertex_2.point]), axis=0)
            return curve_length(edge_points)

        raise WrongEdgeTypeException(self.type)

    def rotate(self, angle: List[float], axis: List[float] = None, origin: List[float] = None) -> "Vertex":
        """Rotates all points in this edge (except start and end Vertex) around an
        arbitrary axis and origin (be careful with projected edges, geometry isn't rotated!)"""
        if axis is None:
            axis = [1, 0, 0]

        if origin is None:
            origin = [0, 0, 0]

        # TODO: include/exclude projected edges?
        if self.type == "line":
            points = None
        elif self.type == "project":
            points = self.points
        elif self.type == "arc":
            points = f.arbitrary_rotation(self.points, axis, angle, origin)
        elif self.type == "spline":
            points = [f.arbitrary_rotation(p, axis, angle, origin) for p in self.points]
        else:
            raise WrongEdgeTypeException(self.type)

        return Edge(self.block_index_1, self.block_index_2, points)

    def __repr__(self):
        return f"{self.type} {self.vertex_1.mesh_index} {self.vertex_2.mesh_index} {self.point_list}"
